import os
import socket
import io
import datetime
import calendar
import math

from flask import Flask, render_template, request, redirect, url_for, flash, send_file, g
from waitress import serve
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from database import get_db, init_db

app = Flask(__name__)
# La clave de sesión y el modo debug ahora se configuran por variable de entorno.
# Si no se define REBELION_SECRET_KEY, se genera una al arrancar (las sesiones/flash
# se invalidan al reiniciar el server, pero nunca queda una clave fija en el código).
app.secret_key = os.environ.get("REBELION_SECRET_KEY") or os.urandom(24)
DEBUG = os.environ.get("REBELION_DEBUG", "0") == "1"

init_db()


# ================= CONEXIÓN A LA BASE (una por request, siempre se cierra) =================

def get_conn():
    """Devuelve la conexión SQLite de este request, creándola si hace falta.
    Se cierra sola en teardown_appcontext, incluso si la vista lanza una excepción
    (antes, un error a mitad de una ruta podía dejar la conexión abierta)."""
    if "db" not in g:
        g.db = get_db()
    return g.db


@app.teardown_appcontext
def cerrar_conn(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ================= FILTROS DE TEMPLATE =================

@app.template_filter("money")
def money(value):
    return f"${value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@app.template_filter("num_fmt")
def num_fmt(value):
    try:
        n = float(value)
        if abs(n - round(n)) < 1e-9:
            return f"{int(round(n)):,}".replace(",", ".")
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "0"

@app.template_filter("int_fmt")
def int_fmt(value):
    try:
        return int(round(float(value)))
    except (ValueError, TypeError):
        return 0


# ================= HELPERS DE FORMULARIO =================

def form_float(campo, default=None):
    """Lee un campo numérico del form. Devuelve None (en vez de reventar con un
    500) si el campo falta o no es un número válido."""
    val = request.form.get(campo)
    if val is None or val.strip() == "":
        return default
    try:
        return float(val)
    except ValueError:
        return None


def form_int(campo, default=None):
    val = form_float(campo)
    if val is None:
        return default
    return int(round(val))


def producto_config_form():
    """Lee la configuración de stock/venta de V3."""
    modo = request.form.get("modo_stock", "exacto")
    if modo not in ("exacto", "rendimiento", "libre"):
        modo = "exacto"
    unidad_venta = request.form.get("unidad_venta", "unidad").strip() or "unidad"
    unidad_stock = request.form.get("unidad_stock", unidad_venta).strip() or unidad_venta
    rendimiento = form_float("rendimiento", 1)
    if rendimiento is None or rendimiento <= 0:
        return None
    return modo, unidad_stock, unidad_venta, rendimiento


def rango_mes(mes_str):
    """Convierte 'YYYY-MM' en (inicio, fin_exclusivo) como strings comparables
    con fecha_hora (TEXT). A diferencia de strftime('%Y-%m', fecha_hora)=?,
    esta comparación por rango puede usar un índice sobre fecha_hora."""
    inicio = datetime.datetime.strptime(mes_str, "%Y-%m")
    ultimo_dia = calendar.monthrange(inicio.year, inicio.month)[1]
    fin = inicio.replace(day=ultimo_dia, hour=23, minute=59, second=59)
    return inicio.strftime("%Y-%m-%d 00:00:00"), fin.strftime("%Y-%m-%d 23:59:59")


# ================= RUTAS PRINCIPALES =================

@app.route("/")
def index():
    db = get_conn()
    # La disponibilidad libre no representa un stock físico controlable.
    # Por eso nunca debe disparar alertas de stock mínimo.
    productos = db.execute("""
        SELECT *, CASE
            WHEN modo_stock != 'libre' AND stock <= stock_minimo THEN 1
            ELSE 0
        END stock_bajo
        FROM productos WHERE activo=1 ORDER BY nombre
    """).fetchall()
    stock_bajo = [p for p in productos if p["stock_bajo"]]

    # Evento vigente: se toma el abierto más reciente.
    evento = db.execute("""
        SELECT * FROM eventos WHERE estado='abierto'
        ORDER BY fecha DESC, id DESC LIMIT 1
    """).fetchone()

    ventas_evento = margen_evento = perdidas_evento_valor = 0
    efectivo_evento = transferencia_evento = 0
    if evento:
        ventas_evento = db.execute(
            "SELECT COALESCE(SUM(total),0) FROM ventas WHERE evento_id=?",
            (evento["id"],)).fetchone()[0]

        margen_ventas = db.execute("""
            SELECT COALESCE(SUM(vi.cantidad*(vi.precio_unitario-vi.costo_unitario)),0)
            FROM venta_items vi JOIN ventas v ON v.id=vi.venta_id
            WHERE v.evento_id=?
        """, (evento["id"],)).fetchone()[0]
        perdidas_evento_valor = db.execute("""
            SELECT COALESCE(SUM(m.cantidad * COALESCE(m.costo_unitario, p.costo)),0)
            FROM movimientos m JOIN productos p ON p.id=m.producto_id
            WHERE m.evento_id=? AND m.tipo='perdida'
        """, (evento["id"],)).fetchone()[0]
        gastos_evento_valor = db.execute(
            "SELECT COALESCE(SUM(monto),0) FROM gastos WHERE evento_id=?",
            (evento["id"],)).fetchone()[0]
        margen_evento = margen_ventas - perdidas_evento_valor - gastos_evento_valor + (evento["bono_rebelion"] or 0)

        efectivo_evento = db.execute(
            "SELECT COALESCE(SUM(total),0) FROM ventas WHERE evento_id=? AND medio_pago='efectivo'",
            (evento["id"],)).fetchone()[0]
        transferencia_evento = db.execute(
            "SELECT COALESCE(SUM(total),0) FROM ventas WHERE evento_id=? AND medio_pago='transferencia'",
            (evento["id"],)).fetchone()[0]

    # Indicador secundario de stock: sigue disponible, pero deja de competir con la recaudación.
    resumen_stock = db.execute(
        "SELECT COALESCE(SUM(stock*costo),0) valor, COALESCE(SUM(stock),0) unidades "
        "FROM productos WHERE activo=1"
    ).fetchone()
    valor_stock = resumen_stock["valor"]
    total_unidades_stock = resumen_stock["unidades"]

    mes_actual = datetime.datetime.now().strftime("%Y-%m")
    inicio, fin = rango_mes(mes_actual)
    perdidas_mes = db.execute("""
        SELECT COALESCE(SUM(m.cantidad * COALESCE(m.costo_unitario, p.costo)), 0) as valor_perdida,
               COALESCE(SUM(m.cantidad), 0) as cant_perdida
        FROM movimientos m
        JOIN productos p ON p.id = m.producto_id
        WHERE m.tipo = 'perdida' AND m.fecha_hora BETWEEN ? AND ?
    """, (inicio, fin)).fetchone()

    # Recaudación y bono acumulados de todos los eventos.
    recaudacion_total = db.execute(
        "SELECT COALESCE(SUM(total),0) FROM ventas"
    ).fetchone()[0]
    bono_total = db.execute(
        "SELECT COALESCE(SUM(bono_rebelion),0) FROM eventos"
    ).fetchone()[0]
    margen_total_ventas = db.execute("""
        SELECT COALESCE(SUM(vi.cantidad*(vi.precio_unitario-vi.costo_unitario)),0)
        FROM venta_items vi
    """).fetchone()[0]
    perdidas_total = db.execute("""
        SELECT COALESCE(SUM(m.cantidad * COALESCE(m.costo_unitario, p.costo)),0)
        FROM movimientos m JOIN productos p ON p.id=m.producto_id
        WHERE m.tipo='perdida'
    """).fetchone()[0]
    ganancias_local = margen_total_ventas - perdidas_total + bono_total - gastos_total if 'gastos_total' in locals() else margen_total_ventas - perdidas_total + bono_total

    gastos_total = db.execute("SELECT COALESCE(SUM(monto),0) FROM gastos").fetchone()[0]
    caja_disponible = recaudacion_total + bono_total - gastos_total

    ultimos_eventos = db.execute("""
        SELECT e.*, COALESCE(SUM(v.total), 0) as recaudacion
        FROM eventos e
        LEFT JOIN ventas v ON v.evento_id = e.id
        GROUP BY e.id
        ORDER BY e.fecha DESC, e.id DESC
        LIMIT 5
    """).fetchall()

    hoy = datetime.date.today().isoformat()
    proximas_actividades = db.execute("""
        SELECT * FROM actividades
        WHERE estado='programada' AND fecha >= ?
        ORDER BY fecha ASC,
                 CASE WHEN hora_inicio='' THEN '99:99' ELSE hora_inicio END ASC, id ASC
        LIMIT 5
    """, (hoy,)).fetchall()

    return render_template("index.html", productos=productos, stock_bajo=stock_bajo,
                           evento=evento, ventas_evento=ventas_evento,
                           margen_evento=margen_evento,
                           efectivo_evento=efectivo_evento,
                           transferencia_evento=transferencia_evento,
                           valor_stock=valor_stock,
                           total_unidades_stock=total_unidades_stock,
                           perdidas_mes=perdidas_mes,
                           recaudacion_total=recaudacion_total,
                           bono_total=bono_total,
                           ganancias_local=ganancias_local,
                           gastos_total=gastos_total,
                           caja_disponible=caja_disponible,
                           ultimos_eventos=ultimos_eventos,
                           proximas_actividades=proximas_actividades,
                           mes_actual=mes_actual)


@app.route("/productos")
def productos():
    db = get_conn()
    productos = db.execute("SELECT * FROM productos WHERE activo=1 ORDER BY nombre").fetchall()
    return render_template("productos.html", productos=productos)


@app.route("/productos/nuevo", methods=["GET", "POST"])
def nuevo_producto():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        categoria = request.form.get("categoria", "")
        costo = form_float("costo")
        precio = form_float("precio")
        stock = form_float("stock")
        stock_minimo = form_float("stock_minimo")
        config = producto_config_form()

        if not nombre or None in (costo, precio, stock, stock_minimo) or config is None:
            flash("Revisá los datos: nombre y los campos numéricos son obligatorios.", "danger")
            return render_template("producto_form.html", producto=None)
        modo, unidad_stock, unidad_venta, rendimiento = config
        if costo < 0 or precio < 0 or stock < 0 or stock_minimo < 0:
            flash("Los valores numéricos no pueden ser negativos.", "danger")
            return render_template("producto_form.html", producto=None)
        if modo == "exacto":
            rendimiento = 1
        if modo == "libre":
            stock_minimo = 0

        db = get_conn()
        cur = db.execute("""INSERT INTO productos
            (nombre,categoria,costo,precio,stock,stock_minimo,unidad,modo_stock,unidad_stock,unidad_venta,rendimiento)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (nombre, categoria, costo, precio, stock, stock_minimo, unidad_venta,
             modo, unidad_stock, unidad_venta, rendimiento))
        if stock > 0:
            db.execute("""INSERT INTO movimientos(producto_id,tipo,cantidad,motivo)
                          VALUES (?,'entrada',?,'Stock inicial')""", (cur.lastrowid, stock))
        db.commit()
        flash("Producto creado correctamente.", "success")
        return redirect(url_for("productos"))
    return render_template("producto_form.html", producto=None)


@app.route("/productos/<int:producto_id>/editar", methods=["GET", "POST"])
def editar_producto(producto_id):
    db = get_conn()
    producto = db.execute("SELECT * FROM productos WHERE id=?", (producto_id,)).fetchone()
    if not producto:
        flash("Producto inexistente.", "danger")
        return redirect(url_for("productos"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        categoria = request.form.get("categoria", "")
        costo = form_float("costo")
        precio = form_float("precio")
        stock_minimo = form_float("stock_minimo")
        config = producto_config_form()

        if not nombre or None in (costo, precio, stock_minimo) or config is None:
            flash("Revisá los datos: nombre y los campos numéricos son obligatorios.", "danger")
            return render_template("producto_form.html", producto=producto)
        modo, unidad_stock, unidad_venta, rendimiento = config
        if costo < 0 or precio < 0 or stock_minimo < 0:
            flash("Los valores numéricos no pueden ser negativos.", "danger")
            return render_template("producto_form.html", producto=producto)
        if modo == "exacto":
            rendimiento = 1
        if modo == "libre":
            stock_minimo = 0

        db.execute("""UPDATE productos
                      SET nombre=?, categoria=?, costo=?, precio=?, stock_minimo=?, unidad=?,
                          modo_stock=?, unidad_stock=?, unidad_venta=?, rendimiento=?
                      WHERE id=?""",
                   (nombre, categoria, costo, precio, stock_minimo, unidad_venta,
                    modo, unidad_stock, unidad_venta, rendimiento, producto_id))
        db.commit()
        flash("Producto actualizado correctamente.", "success")
        return redirect(url_for("productos"))

    return render_template("producto_form.html", producto=producto)


@app.route("/productos/<int:producto_id>/eliminar", methods=["POST"])
def eliminar_producto(producto_id):
    db = get_conn()
    producto = db.execute("SELECT * FROM productos WHERE id=?", (producto_id,)).fetchone()
    if not producto:
        flash("Producto inexistente.", "danger")
        return redirect(url_for("productos"))

    # Baja lógica (activo=0), no DELETE: movimientos, venta_items e historial de
    # eventos ya cargados hacen referencia a este producto_id. Borrarlo de la
    # tabla rompería esos reportes o violaría la foreign key.
    db.execute("UPDATE productos SET activo=0 WHERE id=?", (producto_id,))
    db.commit()
    flash(f'"{producto["nombre"]}" se eliminó del stock activo.', "warning")
    return redirect(url_for("productos"))


@app.route("/productos/eliminados")
def productos_eliminados():
    db = get_conn()
    productos = db.execute("SELECT * FROM productos WHERE activo=0 ORDER BY nombre").fetchall()
    return render_template("productos_eliminados.html", productos=productos)


@app.route("/productos/<int:producto_id>/reactivar", methods=["POST"])
def reactivar_producto(producto_id):
    db = get_conn()
    producto = db.execute("SELECT * FROM productos WHERE id=?", (producto_id,)).fetchone()
    if not producto:
        flash("Producto inexistente.", "danger")
        return redirect(url_for("productos_eliminados"))

    db.execute("UPDATE productos SET activo=1 WHERE id=?", (producto_id,))
    db.commit()
    flash(f'"{producto["nombre"]}" se restauró al stock activo.', "success")
    return redirect(url_for("productos_eliminados"))


@app.route("/productos/<int:producto_id>/stock", methods=["POST"])
def modificar_stock(producto_id):
    cantidad = form_float("cantidad")
    tipo = request.form.get("tipo", "")
    motivo = request.form.get("motivo", "")

    if cantidad is None or cantidad < 0:
        flash("Cantidad inválida.", "danger")
        return redirect(url_for("productos"))

    db = get_conn()
    p = db.execute("SELECT * FROM productos WHERE id=?", (producto_id,)).fetchone()
    if not p:
        flash("Producto inexistente.", "danger")
        return redirect(url_for("productos"))

    # Los movimientos manuales siempre trabajan en la unidad física de stock.
    if p["modo_stock"] == "libre":
        flash("Este producto tiene disponibilidad libre: no requiere ajuste de stock.", "warning")
        return redirect(url_for("productos"))

    if tipo == "entrada":
        nuevo = p["stock"] + cantidad
    elif tipo in ("salida", "perdida"):
        nuevo = p["stock"] - cantidad
        if nuevo < -1e-9:
            flash("No hay suficiente stock.", "danger")
            return redirect(url_for("productos"))
    else:
        nuevo = cantidad
        tipo = "ajuste"

    db.execute("UPDATE productos SET stock=? WHERE id=?", (max(0, nuevo), producto_id))
    db.execute("""INSERT INTO movimientos(producto_id,tipo,cantidad,motivo,costo_unitario)
                  VALUES (?,?,?,?,?)""",
               (producto_id, tipo, cantidad, motivo, p["costo"] if tipo == "perdida" else None))
    db.commit()

    msg = "Pérdida registrada correctamente." if tipo == "perdida" else "Stock actualizado."
    flash(msg, "warning" if tipo == "perdida" else "success")
    return redirect(url_for("productos"))


@app.route("/movimientos")
def movimientos():
    db = get_conn()
    mes = request.args.get("mes", datetime.datetime.now().strftime("%Y-%m"))
    inicio, fin = rango_mes(mes)
    movs = db.execute("""
        SELECT m.*, p.nombre as producto_nombre,
               CASE WHEN m.tipo IN ('venta','perdida') THEN p.unidad_venta ELSE p.unidad_stock END AS unidad,
               e.nombre as evento_nombre
        FROM movimientos m
        JOIN productos p ON p.id = m.producto_id
        LEFT JOIN eventos e ON e.id = m.evento_id
        WHERE m.fecha_hora BETWEEN ? AND ?
        ORDER BY m.fecha_hora DESC, m.id DESC
    """, (inicio, fin)).fetchall()
    return render_template("movimientos.html", movimientos=movs, mes=mes)


@app.route("/caja")
def caja():
    db = get_conn()
    gastos = db.execute("""
        SELECT g.*, e.nombre AS evento_nombre
        FROM gastos g
        LEFT JOIN eventos e ON e.id=g.evento_id
        ORDER BY g.fecha_hora DESC, g.id DESC
    """).fetchall()
    total_recaudado = db.execute("SELECT COALESCE(SUM(total),0) FROM ventas").fetchone()[0]
    total_bonos = db.execute("SELECT COALESCE(SUM(bono_rebelion),0) FROM eventos").fetchone()[0]
    total_gastos = db.execute("SELECT COALESCE(SUM(monto),0) FROM gastos").fetchone()[0]
    disponible = total_recaudado + total_bonos - total_gastos
    eventos_lista = db.execute("SELECT * FROM eventos ORDER BY fecha DESC, id DESC").fetchall()
    return render_template("caja.html", gastos=gastos, total_recaudado=total_recaudado,
                           total_bonos=total_bonos, total_gastos=total_gastos,
                           disponible=disponible, eventos=eventos_lista)


@app.route("/caja/gasto", methods=["POST"])
def nuevo_gasto():
    concepto = request.form.get("concepto", "").strip()
    categoria = request.form.get("categoria", "Otro").strip() or "Otro"
    monto = form_float("monto")
    evento_id = form_int("evento_id")
    notas = request.form.get("notas", "").strip()
    if not concepto or monto is None or monto <= 0:
        flash("Concepto y un monto mayor a 0 son obligatorios.", "danger")
        return redirect(url_for("caja"))
    db = get_conn()
    if evento_id:
        ev = db.execute("SELECT id FROM eventos WHERE id=?", (evento_id,)).fetchone()
        if not ev:
            evento_id = None
    db.execute("INSERT INTO gastos(concepto,categoria,monto,evento_id,notas) VALUES(?,?,?,?,?)",
               (concepto, categoria, monto, evento_id, notas))
    db.commit()
    flash("Gasto registrado correctamente.", "success")
    return redirect(url_for("caja"))


@app.route("/caja/gasto/<int:gasto_id>/eliminar", methods=["POST"])
def eliminar_gasto(gasto_id):
    db = get_conn()
    cur = db.execute("DELETE FROM gastos WHERE id=?", (gasto_id,))
    if cur.rowcount:
        db.commit()
        flash("Gasto eliminado.", "success")
    else:
        flash("Gasto no encontrado.", "danger")
    return redirect(url_for("caja"))


@app.route("/eventos")
def eventos():
    db = get_conn()
    vigente = db.execute("""
        SELECT e.*, COALESCE(SUM(v.total),0) recaudacion
        FROM eventos e
        LEFT JOIN ventas v ON v.evento_id=e.id
        WHERE e.estado='abierto'
        GROUP BY e.id
        ORDER BY e.fecha DESC,e.id DESC
        LIMIT 1
    """).fetchone()
    historial = db.execute("""
        SELECT e.*,COALESCE(SUM(v.total),0) recaudacion
        FROM eventos e LEFT JOIN ventas v ON v.evento_id=e.id
        WHERE e.estado='cerrado'
        GROUP BY e.id ORDER BY e.fecha DESC,e.id DESC
    """).fetchall()
    return render_template("eventos.html", evento=vigente, eventos=historial, hoy=datetime.datetime.now().strftime("%Y-%m-%d"))


@app.route("/eventos/nuevo", methods=["POST"])
def nuevo_evento():
    nombre = request.form.get("nombre", "").strip()
    fecha = request.form.get("fecha", "").strip()
    notas = request.form.get("notas", "").strip()
    nombres = request.form.getlist("responsable_nombre")
    roles = request.form.getlist("responsable_rol")
    inicios = request.form.getlist("responsable_inicio")
    fines = request.form.getlist("responsable_fin")
    notas_resp = request.form.getlist("responsable_notas")

    if not nombre or not fecha:
        flash("Nombre y fecha son obligatorios.", "danger")
        return redirect(url_for("eventos"))

    filas_resp = []
    for i, raw_nombre in enumerate(nombres):
        n = raw_nombre.strip()
        if not n:
            continue
        rol = roles[i].strip() if i < len(roles) and roles[i].strip() else "General"
        if rol not in ("General", "Caja", "Cocina"):
            rol = "General"
        inicio = inicios[i].strip() if i < len(inicios) else ""
        fin = fines[i].strip() if i < len(fines) else ""
        nota = notas_resp[i].strip() if i < len(notas_resp) else ""
        if bool(inicio) != bool(fin):
            flash(f"Completá inicio y fin del turno de {n} o dejalos ambos vacíos.", "danger")
            return redirect(url_for("eventos"))
        filas_resp.append((n, rol, inicio, fin, nota))

    if not filas_resp:
        flash("Cada evento debe tener al menos un responsable.", "danger")
        return redirect(url_for("eventos"))

    db = get_conn()
    vigente = db.execute("SELECT id FROM eventos WHERE estado='abierto' LIMIT 1").fetchone()
    if vigente:
        flash("Ya hay un evento vigente. Cerralo antes de crear otro.", "danger")
        return redirect(url_for("eventos"))
    cur = db.execute("INSERT INTO eventos(nombre,fecha,notas,bono_rebelion) VALUES(?,?,?,0)",
                     (nombre, fecha, notas))
    evento_id = cur.lastrowid
    db.executemany("""INSERT INTO evento_responsables(evento_id,nombre,rol,hora_inicio,hora_fin,notas)
                      VALUES(?,?,?,?,?,?)""",
                   [(evento_id, n, r, hi, hf, no) for n, r, hi, hf, no in filas_resp])
    db.commit()
    flash("Evento creado con sus responsables. El bono se carga al cerrar el evento.", "success")
    return redirect(url_for("evento", evento_id=evento_id))


@app.route("/eventos/<int:evento_id>")
def evento(evento_id):
    db = get_conn()
    evento = db.execute("SELECT * FROM eventos WHERE id=?", (evento_id,)).fetchone()
    if not evento:
        return "Evento no encontrado", 404

    ventas = db.execute("SELECT * FROM ventas WHERE evento_id=? ORDER BY id DESC", (evento_id,)).fetchall()

    pv = db.execute("""SELECT p.nombre,p.unidad,SUM(vi.cantidad) cantidad,
                     SUM(vi.cantidad*vi.precio_unitario) total,
                     SUM(vi.cantidad*(vi.precio_unitario-vi.costo_unitario)) margen
                     FROM venta_items vi JOIN ventas v ON v.id=vi.venta_id
                     JOIN productos p ON p.id=vi.producto_id
                     WHERE v.evento_id=? GROUP BY p.id ORDER BY total DESC""", (evento_id,)).fetchall()

    recaudacion = sum(v["total"] for v in ventas)
    margen_ventas = sum(p["margen"] for p in pv)

    efectivo = sum(v["total"] for v in ventas if v["medio_pago"] == "efectivo")
    transferencia = sum(v["total"] for v in ventas if v["medio_pago"] == "transferencia")

    perdidas_evento = db.execute("""
        SELECT m.*, p.nombre as producto_nombre, p.unidad,
               (m.cantidad * COALESCE(m.costo_unitario, p.costo)) as costo_total
        FROM movimientos m
        JOIN productos p ON p.id = m.producto_id
        WHERE m.evento_id = ? AND m.tipo = 'perdida'
        ORDER BY m.id DESC
    """, (evento_id,)).fetchall()

    valor_total_perdidas = sum(p["costo_total"] for p in perdidas_evento)
    gastos_evento = db.execute("""
        SELECT * FROM gastos WHERE evento_id=? ORDER BY fecha_hora DESC, id DESC
    """, (evento_id,)).fetchall()
    total_gastos_evento = sum(g["monto"] for g in gastos_evento)
    margen = margen_ventas - valor_total_perdidas
    resultado_evento = margen + (evento["bono_rebelion"] or 0) - total_gastos_evento
    caja_evento = recaudacion + (evento["bono_rebelion"] or 0) - total_gastos_evento
    responsables = db.execute("""
        SELECT * FROM evento_responsables
        WHERE evento_id=?
        ORDER BY CASE rol WHEN 'Caja' THEN 1 WHEN 'Cocina' THEN 2 ELSE 3 END, hora_inicio, id
    """, (evento_id,)).fetchall()

    return render_template("evento.html", evento=evento, ventas=ventas,
                           productos_vendidos=pv, recaudacion=recaudacion, margen=margen,
                           efectivo=efectivo, transferencia=transferencia,
                           perdidas_evento=perdidas_evento, valor_total_perdidas=valor_total_perdidas,
                           gastos_evento=gastos_evento, total_gastos_evento=total_gastos_evento,
                           caja_evento=caja_evento, resultado_evento=resultado_evento,
                           responsables=responsables)


@app.route("/eventos/<int:evento_id>/responsables", methods=["POST"])
def agregar_responsable(evento_id):
    nombre = request.form.get("nombre", "").strip()
    rol = request.form.get("rol", "General").strip()
    hora_inicio = request.form.get("hora_inicio", "").strip()
    hora_fin = request.form.get("hora_fin", "").strip()
    notas = request.form.get("notas", "").strip()
    if rol not in ("General", "Caja", "Cocina"):
        rol = "General"
    if not nombre:
        flash("El nombre del responsable es obligatorio.", "danger")
        return redirect(url_for("evento", evento_id=evento_id))
    if bool(hora_inicio) != bool(hora_fin):
        flash("Completá inicio y fin del turno o dejalos ambos vacíos.", "danger")
        return redirect(url_for("evento", evento_id=evento_id))
    db = get_conn()
    evento = db.execute("SELECT id FROM eventos WHERE id=?", (evento_id,)).fetchone()
    if not evento:
        return "Evento no encontrado", 404
    db.execute("""INSERT INTO evento_responsables(evento_id,nombre,rol,hora_inicio,hora_fin,notas)
                  VALUES(?,?,?,?,?,?)""", (evento_id,nombre,rol,hora_inicio,hora_fin,notas))
    db.commit()
    flash("Responsable agregado al evento.", "success")
    return redirect(url_for("evento", evento_id=evento_id))


@app.route("/eventos/<int:evento_id>/responsables/<int:responsable_id>/eliminar", methods=["POST"])
def eliminar_responsable(evento_id, responsable_id):
    db = get_conn()
    db.execute("DELETE FROM evento_responsables WHERE id=? AND evento_id=?", (responsable_id, evento_id))
    db.commit()
    flash("Responsable eliminado.", "success")
    return redirect(url_for("evento", evento_id=evento_id))


@app.route("/eventos/<int:evento_id>/bono", methods=["POST"])
def actualizar_bono(evento_id):
    bono = form_float("bono_rebelion")
    if bono is None or bono < 0:
        flash("El bono debe ser un valor igual o mayor a 0.", "danger")
        return redirect(url_for("evento", evento_id=evento_id))
    db = get_conn()
    evento = db.execute("SELECT id, estado FROM eventos WHERE id=?", (evento_id,)).fetchone()
    if not evento:
        return "Evento no encontrado", 404
    if evento["estado"] != "cerrado":
        flash("El bono se registra únicamente al cerrar el evento.", "danger")
        return redirect(url_for("evento", evento_id=evento_id))
    db.execute("UPDATE eventos SET bono_rebelion=? WHERE id=?", (bono, evento_id))
    db.commit()
    flash("Bono Rebelión de cierre actualizado.", "success")
    return redirect(url_for("evento", evento_id=evento_id))


@app.route("/eventos/<int:evento_id>/venta", methods=["GET", "POST"])
def nueva_venta(evento_id):
    db = get_conn()
    evento = db.execute("SELECT * FROM eventos WHERE id=?", (evento_id,)).fetchone()
    if not evento:
        return "Evento no encontrado", 404
    if evento["estado"] != "abierto":
        flash("El evento está cerrado y ya no admite nuevas ventas.", "danger")
        return redirect(url_for("evento", evento_id=evento_id))

    if request.method == "POST":
        producto_ids = request.form.getlist("producto_id")
        cantidades = request.form.getlist("cantidad")
        medio = request.form.get("medio_pago", "transferencia")
        if medio not in ("efectivo", "transferencia"):
            medio = "transferencia"

        cantidades_por_producto = {}
        for raw_id, raw_cantidad in zip(producto_ids, cantidades):
            try:
                producto_id = int(raw_id)
                cantidad = int(float(raw_cantidad))
            except (TypeError, ValueError):
                flash("Hay un producto o cantidad inválida.", "danger")
                return redirect(request.url)
            if cantidad <= 0:
                continue
            cantidades_por_producto[producto_id] = cantidades_por_producto.get(producto_id, 0) + cantidad

        if not cantidades_por_producto:
            flash("Agregá al menos un producto a la venta.", "danger")
            return redirect(request.url)

        productos_seleccionados = []
        for producto_id, cantidad in cantidades_por_producto.items():
            p = db.execute("SELECT * FROM productos WHERE id=? AND activo=1", (producto_id,)).fetchone()
            if not p:
                flash("Producto inexistente.", "danger")
                return redirect(request.url)

            rendimiento = p["rendimiento"] if p["rendimiento"] and p["rendimiento"] > 0 else 1
            if p["modo_stock"] == "libre":
                stock_consumido = 0
                costo_venta = p["costo"]
            elif p["modo_stock"] == "rendimiento":
                disponible_venta = p["stock"] * rendimiento
                if cantidad > disponible_venta + 1e-9:
                    flash(f"Disponibilidad insuficiente para {p['nombre']}: quedan aproximadamente {disponible_venta:.0f} {p['unidad_venta']}.", "danger")
                    return redirect(request.url)
                stock_consumido = cantidad / rendimiento
                costo_venta = p["costo"] / rendimiento
            else:
                if p["stock"] < cantidad:
                    flash(f"Stock insuficiente para {p['nombre']}.", "danger")
                    return redirect(request.url)
                stock_consumido = cantidad
                costo_venta = p["costo"]

            productos_seleccionados.append((p, cantidad, stock_consumido, costo_venta))

        total = sum(cantidad * p["precio"] for p, cantidad, _, _ in productos_seleccionados)
        cur = db.execute("INSERT INTO ventas(evento_id,medio_pago,total) VALUES(?,?,?)",
                         (evento_id, medio, total))
        venta_id = cur.lastrowid

        for p, cantidad, stock_consumido, costo_venta in productos_seleccionados:
            db.execute("""INSERT INTO venta_items
                (venta_id,producto_id,cantidad,costo_unitario,precio_unitario)
                VALUES(?,?,?,?,?)""", (venta_id, p["id"], cantidad, costo_venta, p["precio"]))
            if p["modo_stock"] != "libre":
                db.execute("UPDATE productos SET stock=stock-? WHERE id=?", (stock_consumido, p["id"]))
                db.execute("""INSERT INTO movimientos(producto_id,tipo,cantidad,motivo,evento_id,costo_unitario)
                             VALUES (?,'venta',?,'Venta en evento',?,?)""",
                           (p["id"], stock_consumido, evento_id, p["costo"]))
        db.commit()
        flash("Venta registrada correctamente.", "success")
        # Volver a la pantalla de venta permite registrar operaciones en cadena sin ir y venir.
        return redirect(url_for("nueva_venta", evento_id=evento_id))

    productos = db.execute("SELECT * FROM productos WHERE activo=1 ORDER BY nombre").fetchall()
    return render_template("venta.html", evento=evento, productos=productos)


@app.route("/eventos/<int:evento_id>/perdida", methods=["GET", "POST"])
def nueva_perdida(evento_id):
    db = get_conn()
    evento = db.execute("SELECT * FROM eventos WHERE id=?", (evento_id,)).fetchone()
    if not evento:
        return "Evento no encontrado", 404
    if evento["estado"] != "abierto":
        flash("El evento está cerrado y ya no admite nuevas pérdidas.", "danger")
        return redirect(url_for("evento", evento_id=evento_id))

    if request.method == "POST":
        producto_id = form_int("producto_id")
        cantidad = form_int("cantidad")
        motivo = request.form.get("motivo", "").strip()
        if producto_id is None or cantidad is None or cantidad <= 0 or not motivo:
            flash("Producto, cantidad y motivo son obligatorios.", "danger")
            return redirect(request.url)

        p = db.execute("SELECT * FROM productos WHERE id=? AND activo=1", (producto_id,)).fetchone()
        if not p:
            flash("Producto inexistente.", "danger")
            return redirect(request.url)

        if p["modo_stock"] == "libre":
            flash("Los productos de disponibilidad libre no requieren registrar pérdidas de stock.", "warning")
            return redirect(request.url)

        rendimiento = p["rendimiento"] if p["rendimiento"] and p["rendimiento"] > 0 else 1
        stock_consumido = cantidad / rendimiento if p["modo_stock"] == "rendimiento" else cantidad
        if p["stock"] < stock_consumido:
            flash(f"No hay suficiente disponibilidad de {p['nombre']}.", "danger")
            return redirect(request.url)

        db.execute("UPDATE productos SET stock=stock-? WHERE id=?", (stock_consumido, producto_id))
        db.execute("""INSERT INTO movimientos(producto_id,tipo,cantidad,motivo,evento_id,costo_unitario)
                      VALUES (?,'perdida',?,?,?,?)""",
                   (producto_id, stock_consumido, motivo, evento_id, p["costo"]))
        db.commit()
        flash("Pérdida registrada. Su costo se descuenta del resultado del evento.", "warning")
        return redirect(url_for("evento", evento_id=evento_id))

    productos = db.execute("SELECT * FROM productos WHERE activo=1 AND (modo_stock!='libre') ORDER BY nombre").fetchall()
    return render_template("perdida_form.html", evento=evento, productos=productos)


@app.route("/eventos/<int:evento_id>/cerrar", methods=["POST"])
def cerrar_evento(evento_id):
    db = get_conn()
    evento = db.execute("SELECT id, estado FROM eventos WHERE id=?", (evento_id,)).fetchone()
    if not evento:
        return "Evento no encontrado", 404
    if evento["estado"] == "cerrado":
        flash("El evento ya estaba cerrado.", "warning")
    else:
        db.execute("UPDATE eventos SET estado='cerrado' WHERE id=?", (evento_id,))
        db.commit()
        flash("Evento cerrado. Ahora podés registrar el Bono Rebelión de cierre.", "success")
    return redirect(url_for("evento", evento_id=evento_id))


# ================= AGENDA / CALENDARIO =================

@app.route("/agenda", methods=["GET", "POST"])
def agenda():
    db = get_conn()
    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        fecha = request.form.get("fecha", "").strip()
        hora_inicio = request.form.get("hora_inicio", "").strip()
        hora_fin = request.form.get("hora_fin", "").strip()
        tipo = request.form.get("tipo", "Actividad").strip() or "Actividad"
        notas = request.form.get("notas", "").strip()
        if tipo not in ("Actividad", "Reserva", "Reunión", "Otro"):
            tipo = "Actividad"
        if not titulo or not fecha:
            flash("Título y fecha son obligatorios.", "danger")
            return redirect(url_for("agenda"))
        if bool(hora_inicio) != bool(hora_fin):
            flash("Completá inicio y fin o dejalos ambos vacíos.", "danger")
            return redirect(url_for("agenda", mes=fecha[:7]))
        if hora_inicio and hora_fin and hora_fin <= hora_inicio:
            flash("La hora de fin debe ser posterior a la de inicio.", "danger")
            return redirect(url_for("agenda", mes=fecha[:7]))
        db.execute("""INSERT INTO actividades(titulo,fecha,hora_inicio,hora_fin,tipo,notas)
                      VALUES(?,?,?,?,?,?)""", (titulo,fecha,hora_inicio,hora_fin,tipo,notas))
        db.commit()
        flash("Actividad agregada a la agenda.", "success")
        return redirect(url_for("agenda", mes=fecha[:7]))

    mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    try:
        inicio_mes = datetime.datetime.strptime(mes + "-01", "%Y-%m-%d").date()
    except ValueError:
        inicio_mes = datetime.date.today().replace(day=1)
        mes = inicio_mes.strftime("%Y-%m")
    cal = calendar.Calendar(firstweekday=0)
    semanas = cal.monthdatescalendar(inicio_mes.year, inicio_mes.month)
    fin_mes = (inicio_mes.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    actividades = db.execute("""SELECT * FROM actividades
                               WHERE fecha BETWEEN ? AND ?
                               ORDER BY fecha, CASE WHEN hora_inicio='' THEN '99:99' ELSE hora_inicio END, id""",
                             (inicio_mes.isoformat(), fin_mes.isoformat())).fetchall()
    por_fecha = {}
    for a in actividades:
        por_fecha.setdefault(a["fecha"], []).append(a)
    calendario = []
    for semana in semanas:
        fila = []
        for dia in semana:
            fila.append({"fecha": dia, "en_mes": dia.month == inicio_mes.month, "actividades": por_fecha.get(dia.isoformat(), [])})
        calendario.append(fila)
    prev_month = (inicio_mes - datetime.timedelta(days=1)).replace(day=1).strftime("%Y-%m")
    next_month = (fin_mes + datetime.timedelta(days=1)).replace(day=1).strftime("%Y-%m")
    proximas = db.execute("""SELECT * FROM actividades
                            WHERE estado='programada' AND fecha >= ?
                            ORDER BY fecha, CASE WHEN hora_inicio='' THEN '99:99' ELSE hora_inicio END, id
                            LIMIT 20""", (datetime.date.today().isoformat(),)).fetchall()
    meses_es = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    mes_nombre = f"{meses_es[inicio_mes.month-1]} {inicio_mes.year}"
    return render_template("agenda.html", calendario=calendario, mes=mes, inicio_mes=inicio_mes,
                           mes_nombre=mes_nombre, prev_month=prev_month, next_month=next_month, proximas=proximas,
                           hoy=datetime.date.today().isoformat())


@app.route("/agenda/<int:actividad_id>/eliminar", methods=["POST"])
def eliminar_actividad(actividad_id):
    db = get_conn()
    actividad = db.execute("SELECT fecha FROM actividades WHERE id=?", (actividad_id,)).fetchone()
    if actividad:
        db.execute("DELETE FROM actividades WHERE id=?", (actividad_id,))
        db.commit()
        flash("Actividad eliminada de la agenda.", "success")
        return redirect(url_for("agenda", mes=actividad["fecha"][:7]))
    flash("Actividad no encontrada.", "danger")
    return redirect(url_for("agenda"))


# ================= EXPORTACIONES A EXCEL =================

def _estilar_excel(ws, titulo):
    header_fill = PatternFill(start_color="111111", end_color="111111", fill_type="solid")
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Arial", size=14, bold=True, color="E21B23")
    border_light = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )

    ws.insert_rows(1, 2)
    ws.cell(row=1, column=1, value=f"REBELIÓN - CASA SOCIALISTA: {titulo}").font = title_font

    for col in range(1, ws.max_column + 1):
        cell = ws.cell(row=3, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in range(4, ws.max_row + 1):
        for col in range(1, ws.max_column + 1):
            ws.cell(row=row, column=col).border = border_light

    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.row < 3:
                continue
            val_str = str(cell.value or '')
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 5, 12)


def _responder_excel(wb, filename):
    """Serializa el workbook y arma la respuesta de descarga. Antes esta lógica
    (BytesIO + save + seek + send_file) estaba duplicada en cada ruta de export."""
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, download_name=filename, as_attachment=True,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/exportar/caja")
def exportar_caja():
    db = get_conn()
    gastos = db.execute("""
        SELECT g.id, g.fecha_hora, g.concepto, g.categoria, g.monto, e.nombre AS evento, g.notas
        FROM gastos g LEFT JOIN eventos e ON e.id=g.evento_id
        ORDER BY g.fecha_hora ASC, g.id ASC
    """).fetchall()
    total_recaudado = db.execute("SELECT COALESCE(SUM(total),0) FROM ventas").fetchone()[0]
    total_bonos = db.execute("SELECT COALESCE(SUM(bono_rebelion),0) FROM eventos").fetchone()[0]
    total_gastos = db.execute("SELECT COALESCE(SUM(monto),0) FROM gastos").fetchone()[0]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Caja"
    ws.append(["ID", "Fecha / Hora", "Concepto", "Categoría", "Evento", "Monto ($)", "Notas"])
    for g in gastos:
        ws.append([g["id"], g["fecha_hora"], g["concepto"], g["categoria"], g["evento"] or "General", g["monto"], g["notas"] or ""])
    ws.append([])
    ws.append(["RESUMEN"])
    ws.append(["Recaudación ($)", total_recaudado])
    ws.append(["Bonos ($)", total_bonos])
    ws.append(["Gastos ($)", total_gastos])
    ws.append(["Caja disponible ($)", total_recaudado + total_bonos - total_gastos])
    _estilar_excel(ws, "CAJA Y GASTOS")
    return _responder_excel(wb, "caja_rebelion.xlsx")


@app.route("/exportar/movimientos")
def exportar_movimientos():
    mes = request.args.get("mes", datetime.datetime.now().strftime("%Y-%m"))
    inicio, fin = rango_mes(mes)
    db = get_conn()
    movs = db.execute("""
        SELECT m.id, m.fecha_hora, p.nombre as producto, m.tipo, m.cantidad,
               CASE WHEN m.tipo IN ('venta','perdida') THEN p.unidad_venta ELSE p.unidad_stock END AS unidad,
               m.motivo, e.nombre as evento
        FROM movimientos m
        JOIN productos p ON p.id = m.producto_id
        LEFT JOIN eventos e ON e.id = m.evento_id
        WHERE m.fecha_hora BETWEEN ? AND ?
        ORDER BY m.fecha_hora ASC
    """, (inicio, fin)).fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Movimientos {mes}"

    ws.append(["ID", "Fecha / Hora", "Producto", "Tipo", "Cantidad", "Unidad", "Motivo", "Evento"])
    for m in movs:
        ws.append([
            m["id"], m["fecha_hora"], m["producto"], m["tipo"].capitalize(),
            m["cantidad"], m["unidad"], m["motivo"] or "", m["evento"] or "-"
        ])

    _estilar_excel(ws, f"MOVIMIENTOS DEL MES ({mes})")
    return _responder_excel(wb, f"movimientos_{mes}.xlsx")


@app.route("/exportar/evento/<int:evento_id>")
def exportar_evento(evento_id):
    db = get_conn()
    evento = db.execute("SELECT * FROM eventos WHERE id=?", (evento_id,)).fetchone()
    if not evento:
        return "Evento no encontrado", 404

    ventas = db.execute("""
        SELECT v.id, v.fecha_hora, v.medio_pago, v.total
        FROM ventas v WHERE v.evento_id=? ORDER BY v.id ASC
    """, (evento_id,)).fetchall()

    pv = db.execute("""
        SELECT p.nombre, p.categoria, p.unidad,
               SUM(vi.cantidad) as cantidad,
               SUM(vi.cantidad * vi.precio_unitario) as total,
               SUM(vi.cantidad * (vi.precio_unitario - vi.costo_unitario)) as margen
        FROM venta_items vi
        JOIN ventas v ON v.id = vi.venta_id
        JOIN productos p ON p.id = vi.producto_id
        WHERE v.evento_id=?
        GROUP BY p.id
        ORDER BY total DESC
    """, (evento_id,)).fetchall()

    perdidas = db.execute("""
        SELECT p.nombre, p.unidad_stock AS unidad, m.cantidad,
               (m.cantidad * COALESCE(m.costo_unitario,p.costo)) costo_total,
               m.motivo, m.fecha_hora
        FROM movimientos m JOIN productos p ON p.id=m.producto_id
        WHERE m.evento_id=? AND m.tipo='perdida'
        ORDER BY m.id ASC
    """, (evento_id,)).fetchall()

    efectivo = sum(v["total"] for v in ventas if v["medio_pago"] == "efectivo")
    transferencia = sum(v["total"] for v in ventas if v["medio_pago"] == "transferencia")
    total_recaudado = sum(v["total"] for v in ventas)
    total_perdidas = sum(p["costo_total"] for p in perdidas)
    margen_ventas = sum(p["margen"] for p in pv)
    resultado = margen_ventas - total_perdidas + (evento["bono_rebelion"] or 0)

    wb = openpyxl.Workbook()
    ws_prod = wb.active
    ws_prod.title = "Resumen por Producto"
    ws_prod.append(["Producto", "Categoría", "Cantidad Vendida", "Unidad", "Total Recaudado ($)", "Margen de Ganancia ($)"])
    for p in pv:
        ws_prod.append([p["nombre"], p["categoria"], int(round(p["cantidad"])), p["unidad"], p["total"], p["margen"]])
    _estilar_excel(ws_prod, f"RESUMEN EVENTO - {evento['nombre']} ({evento['fecha']})")

    ws_ventas = wb.create_sheet(title="Detalle de Ventas")
    ws_ventas.append(["ID Venta", "Fecha / Hora", "Medio de Pago", "Total ($)"])
    for v in ventas:
        medio = "Efectivo" if v["medio_pago"] == "efectivo" else "Transferencia"
        ws_ventas.append([v["id"], v["fecha_hora"], medio, v["total"]])
    ws_ventas.append([])
    ws_ventas.append(["DESGLOSE"]) 
    ws_ventas.append(["Efectivo ($)", efectivo])
    ws_ventas.append(["Transferencia ($)", transferencia])
    ws_ventas.append(["TOTAL RECAUDADO ($)", total_recaudado])
    ws_ventas.append(["BONO REBELIÓN ($)", evento["bono_rebelion"] or 0])
    ws_ventas.append(["COSTO DE PÉRDIDAS ($)", total_perdidas])
    ws_ventas.append(["RESULTADO DEL EVENTO ($)", resultado])
    _estilar_excel(ws_ventas, f"DETALLE DE VENTAS - {evento['nombre']}")

    ws_perd = wb.create_sheet(title="Pérdidas")
    ws_perd.append(["Producto", "Cantidad", "Unidad", "Costo Total ($)", "Motivo", "Fecha / Hora"])
    for p in perdidas:
        ws_perd.append([p["nombre"], p["cantidad"], p["unidad"], p["costo_total"], p["motivo"], p["fecha_hora"]])
    _estilar_excel(ws_perd, f"PÉRDIDAS - {evento['nombre']}")

    gastos_evento = db.execute("SELECT fecha_hora, concepto, categoria, monto, notas FROM gastos WHERE evento_id=? ORDER BY id ASC", (evento_id,)).fetchall()
    ws_gastos = wb.create_sheet(title="Gastos")
    ws_gastos.append(["Fecha / Hora", "Concepto", "Categoría", "Monto ($)", "Notas"])
    for g in gastos_evento:
        ws_gastos.append([g["fecha_hora"], g["concepto"], g["categoria"], g["monto"], g["notas"] or ""])
    _estilar_excel(ws_gastos, f"GASTOS - {evento['nombre']}")

    nombre_limpio = "".join(c if c.isalnum() else "_" for c in evento["nombre"])
    return _responder_excel(wb, f"evento_{evento_id}_{nombre_limpio}.xlsx")



if __name__ == "__main__":
    try:
        hostname = socket.gethostname()
        local_ips = sorted({
            info[4][0] for info in socket.getaddrinfo(hostname, None, socket.AF_INET)
            if info[4][0] and not info[4][0].startswith("127.")
        })
    except Exception:
        local_ips = []

    print("\nRebelión Stock v2 iniciado.")
    print("PC:       http://127.0.0.1:5000")
    for ip in local_ips:
        print(f"Red local: http://{ip}:5000")
    print("\nLas personas conectadas a la misma red pueden abrir la dirección 'Red local'.")
    print("Para detener el servidor: Ctrl+C\n")
    serve(app, host="0.0.0.0", port=5000, threads=8)
