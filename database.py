import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "rebelion.db"


def get_db():
    """Abre una conexión nueva a la base. Flask la cierra al terminar cada request."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _ensure_column(db, table, column, definition):
    """Agrega una columna a instalaciones existentes sin romper bases previas."""
    cols = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
        activo INTEGER NOT NULL DEFAULT 1,
        modo_stock TEXT NOT NULL DEFAULT 'exacto',
        unidad_stock TEXT NOT NULL DEFAULT 'unidad',
        unidad_venta TEXT NOT NULL DEFAULT 'unidad',
        rendimiento REAL NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        fecha TEXT NOT NULL,
        estado TEXT NOT NULL DEFAULT 'abierto',
        notas TEXT DEFAULT '',
        bono_rebelion REAL NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        evento_id INTEGER NOT NULL,
        fecha_hora TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        medio_pago TEXT NOT NULL DEFAULT 'transferencia',
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
    CREATE TABLE IF NOT EXISTS gastos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_hora TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        concepto TEXT NOT NULL,
        categoria TEXT NOT NULL DEFAULT 'Otro',
        monto REAL NOT NULL,
        evento_id INTEGER,
        notas TEXT DEFAULT '',
        FOREIGN KEY(evento_id) REFERENCES eventos(id)
    );
    CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER NOT NULL,
        tipo TEXT NOT NULL,
        cantidad REAL NOT NULL,
        motivo TEXT DEFAULT '',
        evento_id INTEGER,
        fecha_hora TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        costo_unitario REAL,
        FOREIGN KEY(producto_id) REFERENCES productos(id),
        FOREIGN KEY(evento_id) REFERENCES eventos(id)
    );
    CREATE TABLE IF NOT EXISTS evento_responsables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        evento_id INTEGER NOT NULL,
        nombre TEXT NOT NULL,
        rol TEXT NOT NULL DEFAULT 'General',
        hora_inicio TEXT DEFAULT '',
        hora_fin TEXT DEFAULT '',
        notas TEXT DEFAULT '',
        FOREIGN KEY(evento_id) REFERENCES eventos(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS actividades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT NOT NULL,
        fecha TEXT NOT NULL,
        hora_inicio TEXT DEFAULT '',
        hora_fin TEXT DEFAULT '',
        tipo TEXT NOT NULL DEFAULT 'Actividad',
        notas TEXT DEFAULT '',
        estado TEXT NOT NULL DEFAULT 'programada'
    );

    CREATE INDEX IF NOT EXISTS idx_productos_activo ON productos(activo);
    CREATE INDEX IF NOT EXISTS idx_eventos_estado_fecha ON eventos(estado, fecha DESC);
    CREATE INDEX IF NOT EXISTS idx_ventas_evento ON ventas(evento_id);
    CREATE INDEX IF NOT EXISTS idx_ventas_evento_medio ON ventas(evento_id, medio_pago);
    CREATE INDEX IF NOT EXISTS idx_venta_items_venta ON venta_items(venta_id);
    CREATE INDEX IF NOT EXISTS idx_venta_items_producto ON venta_items(producto_id);
    CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos(fecha_hora);
    CREATE INDEX IF NOT EXISTS idx_gastos_evento ON gastos(evento_id);
    CREATE INDEX IF NOT EXISTS idx_movimientos_producto ON movimientos(producto_id);
    CREATE INDEX IF NOT EXISTS idx_movimientos_evento ON movimientos(evento_id);
    CREATE INDEX IF NOT EXISTS idx_movimientos_tipo_fecha ON movimientos(tipo, fecha_hora);
    CREATE INDEX IF NOT EXISTS idx_responsables_evento ON evento_responsables(evento_id);
    CREATE INDEX IF NOT EXISTS idx_actividades_fecha ON actividades(fecha, hora_inicio);
    """)

    # Migraciones para instalaciones creadas con versiones anteriores.
    _ensure_column(db, "eventos", "bono_rebelion", "REAL NOT NULL DEFAULT 0")
    _ensure_column(db, "movimientos", "costo_unitario", "REAL")
    _ensure_column(db, "productos", "modo_stock", "TEXT NOT NULL DEFAULT 'exacto'")
    _ensure_column(db, "productos", "unidad_stock", "TEXT NOT NULL DEFAULT 'unidad'")
    _ensure_column(db, "productos", "unidad_venta", "TEXT NOT NULL DEFAULT 'unidad'")
    _ensure_column(db, "productos", "rendimiento", "REAL NOT NULL DEFAULT 1")
    # Compatibilidad: los productos creados en V2 usan la misma unidad para stock y venta.
    db.execute("""UPDATE productos
                  SET unidad_stock=unidad
                  WHERE unidad_stock='unidad' AND unidad<>'unidad'""")
    db.execute("""UPDATE productos
                  SET unidad_venta=unidad
                  WHERE unidad_venta='unidad' AND unidad<>'unidad'""")
    db.execute("""UPDATE productos SET rendimiento=1
                  WHERE rendimiento IS NULL OR rendimiento<=0""")

    # Mercado Pago queda absorbido por Transferencia en la nueva interfaz.
    # Se conserva el histórico como dato financiero, pero con una única categoría.
    db.execute("UPDATE ventas SET medio_pago='transferencia' WHERE medio_pago='mercado_pago'")

    db.commit()
    db.close()
