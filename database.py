import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "rebelion.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        categoria TEXT NOT NULL,
        costo REAL NOT NULL DEFAULT 0,
        precio REAL NOT NULL DEFAULT 0,
        stock REAL NOT NULL DEFAULT 0,
        stock_minimo REAL NOT NULL DEFAULT 0,
        unidad TEXT NOT NULL DEFAULT 'unidad',
        activo INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        fecha TEXT NOT NULL,
        estado TEXT NOT NULL DEFAULT 'abierto',
        notas TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        evento_id INTEGER NOT NULL,
        fecha_hora TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        medio_pago TEXT NOT NULL DEFAULT 'efectivo',
        total REAL NOT NULL DEFAULT 0,
        FOREIGN KEY(evento_id) REFERENCES eventos(id)
    );
    CREATE TABLE IF NOT EXISTS venta_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venta_id INTEGER NOT NULL,
        producto_id INTEGER NOT NULL,
        cantidad REAL NOT NULL,
        costo_unitario REAL NOT NULL,
        precio_unitario REAL NOT NULL,
        FOREIGN KEY(venta_id) REFERENCES ventas(id),
        FOREIGN KEY(producto_id) REFERENCES productos(id)
    );
    CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER NOT NULL,
        tipo TEXT NOT NULL,
        cantidad REAL NOT NULL,
        motivo TEXT DEFAULT '',
        evento_id INTEGER,
        fecha_hora TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(producto_id) REFERENCES productos(id),
        FOREIGN KEY(evento_id) REFERENCES eventos(id)
    );
    """)
    db.commit()
    db.close()
