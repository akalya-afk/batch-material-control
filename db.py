"""SQLite schema, seed data and connection helper."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS product (
  code TEXT PRIMARY KEY, name TEXT NOT NULL,
  base_qty INTEGER NOT NULL, std_yield REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bom (
  item TEXT PRIMARY KEY, name TEXT NOT NULL, unit TEXT NOT NULL,
  qty_per_base REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS lot (
  id TEXT PRIMARY KEY,
  item TEXT NOT NULL REFERENCES bom(item),
  status TEXT NOT NULL CHECK (status IN ('Released','Quarantined')),
  received REAL NOT NULL CHECK (received > 0),
  received_date TEXT, hold_reason TEXT
);
CREATE TABLE IF NOT EXISTS orders (
  no TEXT PRIMARY KEY,
  qty INTEGER NOT NULL CHECK (qty > 0),
  status TEXT NOT NULL CHECK (status IN ('Released','In production','Completed')),
  created TEXT
);
CREATE TABLE IF NOT EXISTS issue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no TEXT NOT NULL REFERENCES orders(no),
  item TEXT NOT NULL REFERENCES bom(item),
  lot_id TEXT NOT NULL REFERENCES lot(id),
  qty REAL NOT NULL CHECK (qty > 0),
  by_user TEXT NOT NULL, at TEXT NOT NULL,
  ok INTEGER NOT NULL, why TEXT
);
CREATE TABLE IF NOT EXISTS output (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no TEXT NOT NULL REFERENCES orders(no),
  kind TEXT NOT NULL CHECK (kind IN ('good','scrap')),
  qty INTEGER NOT NULL CHECK (qty > 0),
  reason TEXT, at TEXT NOT NULL
);
"""

def connect(path):
    # isolation_level=None: we open transactions ourselves (BEGIN IMMEDIATE)
    c = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def seed(c):
    c.execute("INSERT INTO product VALUES ('FG-SYR-5L','Syringe 5 mL Luer-lock, sterile',100000,0.98)")
    c.executemany("INSERT INTO bom VALUES (?,?,?,?)", [
        ('RM-PP-001', 'Polypropylene resin, medical grade', 'kg', 700),
        ('RM-EL-014', 'Elastomer piston seal', 'pcs', 102000),
        ('RM-SI-007', 'Silicone oil, lubricant', 'kg', 2.4),
        ('PK-BL-021', 'Blister pack', 'pcs', 101000),
        ('PK-CT-005', 'Shipper carton, 100 per carton', 'pcs', 1000),
    ])
    c.executemany("INSERT INTO lot VALUES (?,?,?,?,?,?)", [
        ('PP-2608-A', 'RM-PP-001', 'Released', 1000, '06 Oct', None),
        ('PP-2609-B', 'RM-PP-001', 'Quarantined', 800, '27 Oct', 'melt-flow test pending'),
        ('PP-2610-C', 'RM-PP-001', 'Released', 600, '20 Oct', None),
        ('EL-2610-A', 'RM-EL-014', 'Released', 250000, '12 Oct', None),
        ('EL-2611-B', 'RM-EL-014', 'Quarantined', 100000, '29 Oct', 'visual inspection pending'),
        ('SI-2605-A', 'RM-SI-007', 'Released', 10, '15 Sep', None),
        ('BL-2609-A', 'PK-BL-021', 'Released', 300000, '02 Oct', None),
        ('CT-2610-A', 'PK-CT-005', 'Released', 3000, '09 Oct', None),
    ])
    c.executemany("INSERT INTO orders VALUES (?,?,?,?)", [
        ('PO-1041', 100000, 'Completed', '28 Oct'),
        ('PO-1042', 100000, 'In production', '30 Oct'),
        ('PO-1043', 50000, 'Released', '31 Oct'),
    ])
    issues = [
        ('PO-1041','RM-PP-001','PP-2608-A',712,'R. Kumar','28 Oct 06:10'),
        ('PO-1041','RM-EL-014','EL-2610-A',103500,'R. Kumar','28 Oct 06:15'),
        ('PO-1041','RM-SI-007','SI-2605-A',2.6,'R. Kumar','28 Oct 06:20'),
        ('PO-1041','PK-BL-021','BL-2609-A',101800,'R. Kumar','28 Oct 06:25'),
        ('PO-1041','PK-CT-005','CT-2610-A',1000,'R. Kumar','28 Oct 06:30'),
        ('PO-1042','RM-PP-001','PP-2608-A',288,'S. Devi','30 Oct 14:05'),
        ('PO-1042','RM-EL-014','EL-2610-A',102000,'S. Devi','30 Oct 14:10'),
        ('PO-1042','RM-SI-007','SI-2605-A',2.4,'S. Devi','30 Oct 14:12'),
        ('PO-1042','PK-BL-021','BL-2609-A',101000,'S. Devi','30 Oct 14:15'),
        ('PO-1042','PK-CT-005','CT-2610-A',1000,'S. Devi','30 Oct 14:18'),
    ]
    c.executemany("INSERT INTO issue(order_no,item,lot_id,qty,by_user,at,ok) VALUES (?,?,?,?,?,?,1)", issues)
    c.executemany("INSERT INTO output(order_no,kind,qty,reason,at) VALUES (?,?,?,?,?)", [
        ('PO-1041','good',48500,None,'29 Oct 14:00 Shift A'),
        ('PO-1041','good',47900,None,'29 Oct 22:00 Shift B'),
        ('PO-1041','scrap',1400,'Short shot','29 Oct 22:00 Shift B'),
        ('PO-1041','scrap',900,'Flash / burr','29 Oct 22:00 Shift B'),
        ('PO-1041','scrap',800,'Leak test fail','29 Oct 22:00 Shift B'),
        ('PO-1042','good',30800,None,'31 Oct 14:00 Shift A'),
        ('PO-1042','scrap',500,'Short shot','31 Oct 14:00 Shift A'),
        ('PO-1042','scrap',400,'Flash / burr','31 Oct 14:00 Shift A'),
    ])

def init_db(path):
    c = connect(path)
    c.executescript(SCHEMA)
    if c.execute("SELECT COUNT(*) FROM product").fetchone()[0] == 0:
        seed(c)
    c.close()

def reset_db(path):
    c = connect(path)
    for t in ("output", "issue", "orders", "lot", "bom", "product"):
        c.execute(f"DROP TABLE IF EXISTS {t}")
    c.close()
    init_db(path)
