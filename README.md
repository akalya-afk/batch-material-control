# Batch Material Issue Control (Syringe Line)

A shop floor application that ties every production batch to the exact raw material lots used, blocks unapproved lots, records output and scrap as it happens, and shows actual yield against standard.

## The problem

For each batch (for example 100,000 syringes) the BOM says how much resin, packaging and other material is needed. In practice operators issue material by hand so actual use differs from plan, scrap is recorded only at month end, and nobody records which raw material lots went into which batch.

## The solution

The **production order** is the one place where plan, material issued, output and scrap meet.

1. **Create the order from the BOM.** The BOM is scaled to the order quantity, which fixes the plan.
2. **Issue material by lot.** The operator picks a lot and a quantity. The server checks the rules and records the issue against the order.
3. **Record output and scrap** per shift, with a reason.
4. **Compare actual with standard.** Yield and material variance update straight away.
5. **Close the order.** The record shows which lots went into the batch.

### The rule (enforced on the server, not only on screen)

An issue is accepted only if the order is open, the lot is the right item, the lot is **Released**, and the quantity does not exceed the lot balance. Every refused attempt is kept in the issue log. Issuing more than the plan is allowed and recorded as variance.

- **Yield** = good / (good + scrap), compared with the 98% standard (green within 0.5 points, amber up to 1.5 below, red beyond).
- **Material variance** = issued - plan (fine up to 2%, amber 2 to 5%, red above 5%).

## Run it

```bash
pip install -r requirements.txt
python -m app.main          # open http://127.0.0.1:8000
pytest                      # 13 tests on the rules
```

Or with Docker: `docker build -t batch-issue . && docker run -p 8000:8000 batch-issue`

The database is a local SQLite file (`data.db`), created and seeded on first run. **Reset demo data** in the header restores the sample data.

## Data model

| Table | Key fields |
|---|---|
| product | code, name, base qty (100,000), standard yield |
| bom | item, name, unit, qty per base |
| lot | id, item, status (Released / Quarantined), received, hold reason |
| orders | no, qty, status (Released / In production / Completed) |
| issue | order, item, lot, qty, by, at, ok, why (reason if refused) |
| output | order, good or scrap, qty, reason, at |

The `issue` table is the link that gives traceability both ways: batch to lots, and lot to batches. A lot balance is received minus issued, computed from `issue`.

## API

| Method and path | Purpose |
|---|---|
| GET `/api/state` | Everything the screen needs |
| POST `/api/orders` | Create an order from the BOM |
| POST `/api/issues` | Issue material from a lot (409 if refused) |
| POST `/api/outputs` | Record good output or scrap |
| POST `/api/orders/<no>/close` | Close an order |
| GET `/api/orders/<no>/summary` | Yield, gap to standard, variance, lots used |
| GET `/api/lots/<id>/batches` | Which batches used this lot |
| POST `/api/reset` | Restore demo data |

## Sample data and the two planted cases

BOM per 100,000: resin 700 kg, piston seal 102,000 pcs, silicone oil 2.4 kg, blister 101,000 pcs, carton 1,000 pcs. Orders: PO-1041 (completed, 96.88% yield), PO-1042 (in production, 97.16%), PO-1043 (released).

1. **Quarantined lot about to be issued.** PO-1042 needs 412 kg more resin and the operator has scanned `PP-2609-B`, which is on QC hold. Pressing Issue is refused with HTTP 409 and logged as Blocked. Switching to released lot `PP-2610-C` works.
2. **Lot only partly used.** Issuing 412 kg from `PP-2610-C` (600 kg) leaves 188 kg. Lot `EL-2610-A` is already partly used across PO-1041 and PO-1042 with 44,500 pcs left.

## Stack and what I would change for production

Flask, SQLite, plain HTML/CSS/JavaScript. For production I would move to PostgreSQL (real multi-user concurrency), FastAPI or Flask behind gunicorn, role-based login (operator, QC, supervisor), a QC lot release screen, and barcode scanning of lots. Not built yet: login, QC release screen, and barcode scanning.
