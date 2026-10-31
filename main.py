"""Batch Material Issue Control: API and rules.

The rule that matters lives here, not in the screen:
only Released lots can be issued, and a lot balance can never go negative.
"""
import os
from datetime import datetime

from flask import Flask, g, jsonify, request, send_from_directory

from . import db

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.db")
REASONS = ["Short shot", "Flash / burr", "Leak test fail", "Piston seal defect", "Other"]


def stamp():
    return datetime.now().strftime("%d %b %H:%M")


def r2(x):
    return round(float(x) + 0.0, 2)


def create_app(db_path=None):
    app = Flask(__name__, static_folder=None)
    app.config["DB_PATH"] = db_path or os.environ.get("DB_PATH", DEFAULT_DB)
    db.init_db(app.config["DB_PATH"])

    def conn():
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH"])
        return g.conn

    @app.teardown_appcontext
    def close(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    def fail(code, msg):
        resp = jsonify({"detail": msg})
        resp.status_code = code
        return resp

    def lot_balance(c, lot_id):
        row = c.execute(
            "SELECT received - COALESCE((SELECT SUM(qty) FROM issue WHERE lot_id=lot.id AND ok=1),0) AS bal "
            "FROM lot WHERE id=?", (lot_id,)).fetchone()
        return r2(row["bal"])

    # ---------- pages and data ----------
    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/api/state")
    def state():
        c = conn()
        product = dict(c.execute("SELECT code,name,base_qty AS base,std_yield AS std FROM product").fetchone())
        bom = [dict(r) for r in c.execute("SELECT item,name,unit,qty_per_base AS qty FROM bom ORDER BY rowid")]
        lots = [dict(r) for r in c.execute(
            "SELECT id,item,status,received,received_date AS date,hold_reason AS hold FROM lot ORDER BY rowid")]
        orders = [dict(r) for r in c.execute("SELECT no,qty,status,created AS date FROM orders ORDER BY rowid")]
        issues = [dict(r) for r in c.execute(
            'SELECT id,order_no AS "order",item,lot_id AS lot,qty,by_user AS "by",at AS time,ok,why '
            "FROM issue ORDER BY id")]
        for i in issues:
            i["ok"] = bool(i["ok"])
        outs = [dict(r) for r in c.execute(
            'SELECT order_no AS "order",kind,qty,COALESCE(reason,\'\') AS reason,at AS time FROM output ORDER BY id')]
        return jsonify(product=product, bom=bom, lots=lots, orders=orders, issues=issues, outs=outs,
                       reasons=REASONS)

    # ---------- production orders ----------
    @app.post("/api/orders")
    def create_order():
        body = request.get_json(silent=True) or {}
        qty = body.get("qty")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1000:
            return fail(422, "Quantity must be a whole number of at least 1,000.")
        c = conn()
        n = c.execute("SELECT COALESCE(MAX(CAST(substr(no,4) AS INTEGER)),1000)+1 FROM orders").fetchone()[0]
        no = f"PO-{n}"
        c.execute("INSERT INTO orders VALUES (?,?,?,?)", (no, qty, "Released", stamp()[:6]))
        return jsonify(no=no), 201

    @app.post("/api/orders/<no>/close")
    def close_order(no):
        c = conn()
        o = c.execute("SELECT status FROM orders WHERE no=?", (no,)).fetchone()
        if not o:
            return fail(404, "Order not found.")
        c.execute("UPDATE orders SET status='Completed' WHERE no=?", (no,))
        return jsonify(ok=True)

    # ---------- material issue (the rule) ----------
    @app.post("/api/issues")
    def issue_material():
        body = request.get_json(silent=True) or {}
        order_no, item, lot_id = body.get("order"), body.get("item"), body.get("lot")
        try:
            qty = float(body.get("qty"))
        except (TypeError, ValueError):
            return fail(422, "Enter a quantity above zero.")
        if qty <= 0:
            return fail(422, "Enter a quantity above zero.")
        by = (body.get("by") or "You")[:40]

        c = conn()
        c.execute("BEGIN IMMEDIATE")  # lock so two operators cannot over-issue the same lot
        try:
            o = c.execute("SELECT * FROM orders WHERE no=?", (order_no,)).fetchone()
            b = c.execute("SELECT * FROM bom WHERE item=?", (item,)).fetchone()
            lot = c.execute("SELECT * FROM lot WHERE id=?", (lot_id,)).fetchone()
            if not o or not b:
                c.execute("ROLLBACK")
                return fail(404, "Order or item not found.")
            if not lot:
                c.execute("ROLLBACK")
                return fail(422, "Pick a lot first.")

            why = None
            if o["status"] == "Completed":
                why = "This order is closed."
            elif lot["item"] != item:
                why = f"Lot {lot['id']} is not {b['name']}."
            elif lot["status"] != "Released":
                why = (f"{lot['id']} is quarantined ({lot['hold_reason']}). "
                       "Only released lots can be issued.")
            elif qty > lot_balance(c, lot_id):
                why = f"{lot['id']} has only {lot_balance(c, lot_id):g} {b['unit']} left."

            if why:
                # every refused attempt is kept in the issue log
                c.execute("INSERT INTO issue(order_no,item,lot_id,qty,by_user,at,ok,why) VALUES (?,?,?,?,?,?,0,?)",
                          (order_no, item, lot_id, qty, by, stamp(), why))
                c.execute("COMMIT")
                return fail(409, why)

            c.execute("INSERT INTO issue(order_no,item,lot_id,qty,by_user,at,ok) VALUES (?,?,?,?,?,?,1)",
                      (order_no, item, lot_id, qty, by, stamp()))
            if o["status"] == "Released":
                c.execute("UPDATE orders SET status='In production' WHERE no=?", (order_no,))
            plan = r2(b["qty_per_base"] * o["qty"] / c.execute("SELECT base_qty FROM product").fetchone()[0])
            issued = r2(c.execute("SELECT SUM(qty) FROM issue WHERE order_no=? AND item=? AND ok=1",
                                  (order_no, item)).fetchone()[0])
            left = lot_balance(c, lot_id)
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise

        msg = f"Issued {qty:g} {b['unit']} from {lot_id}. {left:g} {b['unit']} left in the lot."
        over = r2(issued - plan)
        if over > 0:
            msg += f" That is {over:g} {b['unit']} over plan, recorded as variance."
        return jsonify(ok=True, message=msg, warn=over > 0, lot_balance=left)

    # ---------- output and scrap ----------
    @app.post("/api/outputs")
    def record_output():
        body = request.get_json(silent=True) or {}
        order_no, kind, qty = body.get("order"), body.get("kind"), body.get("qty")
        reason = body.get("reason") or None
        if kind not in ("good", "scrap"):
            return fail(422, "Entry must be good output or scrap.")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            return fail(422, "Enter a whole number of syringes.")
        if kind == "scrap" and reason not in REASONS:
            return fail(422, "Pick a scrap reason.")
        if kind == "good":
            reason = None
        c = conn()
        o = c.execute("SELECT status FROM orders WHERE no=?", (order_no,)).fetchone()
        if not o:
            return fail(404, "Order not found.")
        if o["status"] == "Completed":
            return fail(409, "This order is closed.")
        c.execute("INSERT INTO output(order_no,kind,qty,reason,at) VALUES (?,?,?,?,?)",
                  (order_no, kind, qty, reason, stamp() + " (you)"))
        if o["status"] == "Released":
            c.execute("UPDATE orders SET status='In production' WHERE no=?", (order_no,))
        return jsonify(ok=True), 201

    # ---------- reports: yield, variance, traceability ----------
    @app.get("/api/orders/<no>/summary")
    def order_summary(no):
        c = conn()
        o = c.execute("SELECT * FROM orders WHERE no=?", (no,)).fetchone()
        if not o:
            return fail(404, "Order not found.")
        p = c.execute("SELECT * FROM product").fetchone()
        good = c.execute("SELECT COALESCE(SUM(qty),0) FROM output WHERE order_no=? AND kind='good'", (no,)).fetchone()[0]
        scrap = c.execute("SELECT COALESCE(SUM(qty),0) FROM output WHERE order_no=? AND kind='scrap'", (no,)).fetchone()[0]
        total = good + scrap
        y = good / total if total else None
        materials = []
        for b in c.execute("SELECT * FROM bom ORDER BY rowid"):
            plan = r2(b["qty_per_base"] * o["qty"] / p["base_qty"])
            lots = {r["lot_id"]: r2(r["q"]) for r in c.execute(
                "SELECT lot_id,SUM(qty) q FROM issue WHERE order_no=? AND item=? AND ok=1 GROUP BY lot_id", (no, b["item"]))}
            issued = r2(sum(lots.values()))
            materials.append({"item": b["item"], "name": b["name"], "unit": b["unit"], "plan": plan,
                              "issued": issued, "variance": r2(issued - plan),
                              "variance_pct": round((issued - plan) / plan * 100, 1) if plan else 0,
                              "lots": lots})
        return jsonify(order=no, status=o["status"], good=good, scrap=scrap,
                       yield_pct=None if y is None else round(y * 100, 2),
                       standard_pct=round(p["std_yield"] * 100, 2),
                       gap_points=None if y is None else round((y - p["std_yield"]) * 100, 2),
                       excess_scrap=0 if not total else scrap - round(total * (1 - p["std_yield"])),
                       materials=materials)

    @app.get("/api/lots/<lot_id>/batches")
    def lot_batches(lot_id):
        c = conn()
        lot = c.execute("SELECT * FROM lot WHERE id=?", (lot_id,)).fetchone()
        if not lot:
            return fail(404, "Lot not found.")
        rows = c.execute("SELECT order_no, SUM(qty) q FROM issue WHERE lot_id=? AND ok=1 GROUP BY order_no ORDER BY order_no",
                         (lot_id,)).fetchall()
        return jsonify(lot=lot_id, status=lot["status"], received=lot["received"],
                       balance=lot_balance(c, lot_id), batches={r["order_no"]: r2(r["q"]) for r in rows})

    @app.post("/api/reset")
    def reset():
        db.reset_db(app.config["DB_PATH"])
        return jsonify(ok=True)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
