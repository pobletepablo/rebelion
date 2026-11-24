import os
import socket
import io
import datetime
import calendar
import math
import uuid
import hmac
import secrets
from pathlib import Path
from werkzeug.utils import secure_filename

from flask import Flask, render_template, request, redirect, url_for, flash, send_file, g, session
from waitress import serve
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from database import get_db, init_db, DB_PATH
from changelog import VERSION, CAMBIOS

app = Flask(__name__)
MAX_IMAGEN_MB = 10
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGEN_MB * 1024 * 1024
PRODUCT_IMAGE_DIR = Path(app.static_folder) / "productos"
PRODUCT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_PRODUCT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
# Clave de sesión: variable de entorno o archivo secret.key junto a la base
# (se crea una sola vez, así las sesiones sobreviven a reinicios del servidor).
def _clave_secreta():
    env = os.environ.get("REBELION_SECRET_KEY")
    if env:
        return env
    archivo = DB_PATH.parent / "secret.key"
    try:
        if archivo.exists():
            return archivo.read_text().strip()
        clave = secrets.token_hex(32)
        archivo.write_text(clave)
        return clave
    except OSError:
        return secrets.token_hex(32)


app.secret_key = _clave_secreta()
DEBUG = os.environ.get("REBELION_DEBUG", "0") == "1"

init_db()

ADMIN_PASSWORD = os.environ.get("REBELION_ADMIN_PASSWORD", "1917")

# Textos editables de los tickets (Ajustes). Los valores por defecto son los originales.
TICKET_DEFAULTS = {
    "venta_titulo": "COMPROBANTE DE VENTA",
    "venta_pie": "Gracias por colaborar",
    "balance_titulo": "RESUMEN DE ACTIVIDAD",
    "balance_pie": "Rendición consolidada",
    "contacto": "@rebelion.lp",
}


@app.before_request
def requerir_ingreso():
    endpoint = request.endpoint or ""
    if endpoint in {"login", "static"}:
        return
    if not session.get("nombre"):
        return redirect(url_for("login"))

    # Los invitados pueden operar el local, pero no administrar el sistema.
    # No hay usuarios preconfigurados: cualquier nombre entra como invitado.
    admin_only = {
        "movimientos", "caja", "nuevo_gasto", "eliminar_gasto",
        "nuevo_producto", "editar_producto", "eliminar_producto",
        "productos_eliminados", "reactivar_producto", "modificar_stock",
        "nuevo_evento", "agregar_responsable", "eliminar_responsable",
        "actualizar_bono", "nueva_perdida", "cerrar_evento",
        "eliminar_actividad", "ajustes", "exportar_caja", "exportar_movimientos",
        "exportar_evento",
    }
    if endpoint in admin_only and not session.get("es_admin", False):
        flash("Esta función es exclusiva del administrador.", "danger")
        return redirect(url_for("index"))


@app.context_processor
def contexto_usuario():
    return {"usuario_nombre": session.get("nombre"), "es_admin": session.get("es_admin", False),
            "app_version": VERSION}


def textos_ticket():
    """Textos de ticket guardados, completando con los valores por defecto."""
    textos = dict(TICKET_DEFAULTS)
    try:
        for fila in get_conn().execute("SELECT clave, valor FROM config").fetchall():
            if fila["clave"] in textos:
                textos[fila["clave"]] = fila["valor"]
    except Exception:
        pass
    return textos


@app.errorhandler(413)
def archivo_muy_grande(_):
    flash(f"La foto supera los {MAX_IMAGEN_MB} MB. Probá con una más liviana.", "danger")
    return redirect(request.referrer or url_for("productos"))


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


def borrar_imagen_producto(nombre):
    """Elimina del disco una foto que ya no se usa."""
    if nombre:
        try:
            (PRODUCT_IMAGE_DIR / Path(nombre).name).unlink(missing_ok=True)
        except OSError:
            pass


def guardar_imagen_producto(archivo, imagen_actual=""):
    """Guarda una imagen de producto en static/productos y devuelve su nombre."""
    if not archivo or not archivo.filename:
        return imagen_actual or ""
    extension = Path(secure_filename(archivo.filename)).suffix.lower()
    if extension not in ALLOWED_PRODUCT_IMAGE_EXTENSIONS:
        raise ValueError("Formato de imagen no permitido. Usá JPG, PNG o WEBP.")
    nombre = f"{uuid.uuid4().hex}{extension}"
    archivo.save(PRODUCT_IMAGE_DIR / nombre)
    return nombre


def rango_mes(mes_str):
    """Convierte 'YYYY-MM' en (inicio, fin_exclusivo) como strings comparables
    con fecha_hora (TEXT). A diferencia de strftime('%Y-%m', fecha_hora)=?,
    esta comparación por rango puede usar un índice sobre fecha_hora."""
    try:
        inicio = datetime.datetime.strptime(mes_str, "%Y-%m")
    except (TypeError, ValueError):
        inicio = datetime.datetime.now().replace(day=1)
    ultimo_dia = calendar.monthrange(inicio.year, inicio.month)[1]
    fin = inicio.replace(day=ultimo_dia, hour=23, minute=59, second=59)
    return inicio.strftime("%Y-%m-%d 00:00:00"), fin.strftime("%Y-%m-%d 23:59:59")


# ================= RUTAS PRINCIPALES =================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        password = request.form.get("password", "")
        if not nombre:
            flash("Ingresá tu nombre para entrar.", "danger")
            return redirect(url_for("login"))
        if password and not hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
            flash("Contraseña incorrecta. Dejala vacía para entrar como invitado.", "danger")
            return redirect(url_for("login"))
        session.clear()
        session["nombre"] = nombre
        session["es_admin"] = bool(password)
        flash(f"Bienvenido/a, {nombre}.", "success")
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/salir")
def salir():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    db = get_conn()
    evento = db.execute("""
        SELECT * FROM eventos WHERE estado='abierto'
        ORDER BY fecha DESC, id DESC LIMIT 1
    """).fetchone()

    # Los invitados van directo a vender si hay un evento vigente.
    if not session.get("es_admin", False):
        if evento:
            return redirect(url_for("nueva_venta", evento_id=evento["id"]))
        return redirect(url_for("modo_evento"))

    recaudacion_total = db.execute("SELECT COALESCE(SUM(total),0) FROM ventas").fetchone()[0]
    bono_total = db.execute("SELECT COALESCE(SUM(bono_rebelion),0) FROM eventos").fetchone()[0]
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

    proximas_actividades = db.execute("""
        SELECT * FROM actividades
        WHERE estado='programada' AND fecha >= ?
        ORDER BY fecha ASC,
                 CASE WHEN hora_inicio='' THEN '99:99' ELSE hora_inicio END ASC, id ASC
        LIMIT 5
    """, (datetime.date.today().isoformat(),)).fetchall()

    return render_template("index.html", evento=evento, gastos_total=gastos_total,
                           caja_disponible=caja_disponible, ultimos_eventos=ultimos_eventos,
                           proximas_actividades=proximas_actividades,
                           mes_actual=datetime.datetime.now().strftime("%Y-%m"))


@app.route("/modo-evento")
@app.route("/modo-evento/<int:evento_id>")
def modo_evento(evento_id=None):
    db = get_conn()
    if evento_id:
        evento = db.execute("SELECT * FROM eventos WHERE id=?", (evento_id,)).fetchone()
    else:
        evento = db.execute("SELECT * FROM eventos WHERE estado='abierto' ORDER BY fecha DESC,id DESC LIMIT 1").fetchone()
    # Con un evento vigente, la entrada es directo el punto de venta.
    if evento and evento["estado"] == "abierto":
        return redirect(url_for("nueva_venta", evento_id=evento["id"]))
    responsables = []
    if evento:
        responsables = db.execute("SELECT * FROM evento_responsables WHERE evento_id=? ORDER BY CASE rol WHEN 'Caja' THEN 1 WHEN 'Cocina' THEN 2 ELSE 3 END,hora_inicio", (evento["id"],)).fetchall()
    agenda_proxima = db.execute("SELECT * FROM actividades WHERE fecha>=date('now','localtime') ORDER BY fecha,hora_inicio LIMIT 8").fetchall()
    return render_template("modo_evento.html", evento=evento, responsables=responsables, agenda=agenda_proxima)


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
        try:
            imagen = guardar_imagen_producto(request.files.get("imagen"))
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("producto_form.html", producto=None)

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
            (nombre,categoria,costo,precio,stock,stock_minimo,unidad,modo_stock,unidad_stock,unidad_venta,rendimiento,imagen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (nombre, categoria, costo, precio, stock, stock_minimo, unidad_venta,
             modo, unidad_stock, unidad_venta, rendimiento, imagen))
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
        try:
            imagen = guardar_imagen_producto(request.files.get("imagen"), producto["imagen"] or "")
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("producto_form.html", producto=producto)
        if request.form.get("quitar_imagen") == "1" and imagen == (producto["imagen"] or ""):
            imagen = ""

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
                          modo_stock=?, unidad_stock=?, unidad_venta=?, rendimiento=?, imagen=?
                      WHERE id=?""",
                   (nombre, categoria, costo, precio, stock_minimo, unidad_venta,
                    modo, unidad_stock, unidad_venta, rendimiento, imagen, producto_id))
        db.commit()
        if (producto["imagen"] or "") != imagen:
            borrar_imagen_producto(producto["imagen"])
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
    cant_mov, costo_mov = cantidad, (p["costo"] if tipo == "perdida" else None)
    if tipo == "perdida" and p["modo_stock"] == "rendimiento":
        # Las pérdidas se muestran en unidad de venta (ej.: vasos), igual que las del evento.
        rend = p["rendimiento"] if p["rendimiento"] and p["rendimiento"] > 0 else 1
        cant_mov, costo_mov = cantidad * rend, p["costo"] / rend
    db.execute("""INSERT INTO movimientos(producto_id,tipo,cantidad,motivo,costo_unitario)
                  VALUES (?,?,?,?,?)""", (producto_id, tipo, cant_mov, motivo, costo_mov))
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


@app.route("/eventos/<int:evento_id>/gasto", methods=["POST"])
def nuevo_gasto_evento(evento_id):
    concepto = request.form.get("concepto", "").strip()
    categoria = request.form.get("categoria", "Otro").strip() or "Otro"
    monto = form_float("monto")
    notas = request.form.get("notas", "").strip()
    db = get_conn()
    evento = db.execute("SELECT id, estado FROM eventos WHERE id=?", (evento_id,)).fetchone()
    if not evento:
        return "Evento no encontrado", 404
    if not concepto or monto is None or monto <= 0:
        flash("Concepto y un monto mayor a 0 son obligatorios.", "danger")
        return redirect(url_for("evento", evento_id=evento_id))
    db.execute("INSERT INTO gastos(concepto,categoria,monto,evento_id,notas) VALUES(?,?,?,?,?)",
               (concepto, categoria, monto, evento_id, notas))
    db.commit()
    flash("Gasto asociado al evento.", "success")
    return redirect(url_for("evento", evento_id=evento_id))


@app.route("/caja/gasto/<int:gasto_id>/eliminar", methods=["POST"])
def eliminar_gasto(gasto_id):
    db = get_conn()
    gasto = db.execute("SELECT evento_id FROM gastos WHERE id=?", (gasto_id,)).fetchone()
    if not gasto:
        flash("Gasto no encontrado.", "danger")
        return redirect(url_for("caja"))
    db.execute("DELETE FROM gastos WHERE id=?", (gasto_id,))
    db.commit()
    flash("Gasto eliminado.", "success")
    if request.form.get("volver") == "evento" and gasto["evento_id"]:
        return redirect(url_for("evento", evento_id=gasto["evento_id"]) + "#gastos")
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


@app.route("/eventos/<int:evento_id>/ticket")
def ticket_evento(evento_id):
    db = get_conn()
    evento = db.execute("SELECT * FROM eventos WHERE id=?", (evento_id,)).fetchone()
    if not evento:
        return "Evento no encontrado", 404
    ventas = db.execute("SELECT * FROM ventas WHERE evento_id=? ORDER BY id ASC", (evento_id,)).fetchall()
    items = db.execute("""SELECT p.nombre, p.unidad_venta unidad, SUM(vi.cantidad) cantidad,
                         SUM(vi.cantidad*vi.precio_unitario) total
                         FROM venta_items vi JOIN ventas v ON v.id=vi.venta_id
                         JOIN productos p ON p.id=vi.producto_id
                         WHERE v.evento_id=? GROUP BY p.id ORDER BY total DESC""", (evento_id,)).fetchall()
    gastos = db.execute("SELECT * FROM gastos WHERE evento_id=? ORDER BY fecha_hora ASC, id ASC", (evento_id,)).fetchall()
    perdidas = db.execute("""SELECT COALESCE(SUM(m.cantidad*COALESCE(m.costo_unitario,p.costo)),0)
                            FROM movimientos m JOIN productos p ON p.id=m.producto_id
                            WHERE m.evento_id=? AND m.tipo='perdida'""", (evento_id,)).fetchone()[0]
    recaudacion = sum(v["total"] for v in ventas)
    total_gastos = sum(g["monto"] for g in gastos)
    bono = evento["bono_rebelion"] or 0
    resultado = recaudacion - perdidas - total_gastos + bono
    efectivo = sum(v["total"] for v in ventas if v["medio_pago"] == "efectivo")
    transferencia = sum(v["total"] for v in ventas if v["medio_pago"] == "transferencia")
    return render_template("ticket_evento.html", textos=textos_ticket(), evento=evento, items=items, gastos=gastos,
                           recaudacion=recaudacion, total_gastos=total_gastos, perdidas=perdidas,
                           bono=bono, resultado=resultado, efectivo=efectivo, transferencia=transferencia,
                           ventas=ventas)


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
            # El movimiento se registra SIEMPRE (antes se omitía por completo
            # para productos de disponibilidad libre, así que esas ventas no
            # quedaban en /movimientos ni en su exportación a Excel).
            # "cantidad" (no "stock_consumido") y "costo_venta" (no el costo
            # crudo del producto) son los valores correctos acá: antes, para
            # productos con rendimiento, se guardaba la cantidad convertida a
            # la unidad de stock (ej: 0,21 botella) pero la pantalla la
            # etiquetaba como unidad de venta ("0,21 vaso"), y el costo
            # unitario quedaba sin dividir por el rendimiento.
            db.execute("""INSERT INTO movimientos(producto_id,tipo,cantidad,motivo,evento_id,costo_unitario)
                         VALUES (?,'venta',?,'Venta en evento',?,?)""",
                       (p["id"], cantidad, evento_id, costo_venta))
        db.commit()
        flash("Venta registrada correctamente.", "success")
        if request.form.get("imprimir_automatico") == "1":
            return redirect(url_for("ticket_venta", venta_id=venta_id))
        # Volver a la pantalla de venta permite registrar operaciones en cadena sin ir y venir.
        return redirect(url_for("nueva_venta", evento_id=evento_id))

    productos = db.execute("SELECT * FROM productos WHERE activo=1 ORDER BY nombre").fetchall()
    return render_template("venta.html", evento=evento, productos=productos)


@app.route("/ventas/<int:venta_id>/ticket")
def ticket_venta(venta_id):
    db = get_conn()
    venta = db.execute("SELECT v.*,e.nombre evento_nombre,e.fecha evento_fecha FROM ventas v JOIN eventos e ON e.id=v.evento_id WHERE v.id=?", (venta_id,)).fetchone()
    if not venta:
        return "Venta no encontrada", 404
    items = db.execute("SELECT p.nombre,p.unidad_venta unidad,vi.cantidad,vi.precio_unitario,vi.cantidad*vi.precio_unitario total FROM venta_items vi JOIN productos p ON p.id=vi.producto_id WHERE vi.venta_id=? ORDER BY vi.id", (venta_id,)).fetchall()
    return render_template("ticket_venta.html", textos=textos_ticket(), venta=venta, items=items)


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
        es_rendimiento = p["modo_stock"] == "rendimiento"
        stock_consumido = cantidad / rendimiento if es_rendimiento else cantidad
        costo_venta = (p["costo"] / rendimiento) if es_rendimiento else p["costo"]
        if p["stock"] < stock_consumido:
            flash(f"No hay suficiente disponibilidad de {p['nombre']}.", "danger")
            return redirect(request.url)

        db.execute("UPDATE productos SET stock=stock-? WHERE id=?", (stock_consumido, producto_id))
        # "cantidad" (unidad de venta, ej: vasos) y "costo_venta" (costo ya
        # dividido por el rendimiento) — no "stock_consumido" ni el costo
        # crudo — para que coincidan con la unidad que se muestra en
        # /movimientos (unidad_venta para pérdidas). El total en pesos de la
        # pérdida (cantidad × costo) da lo mismo en ambos esquemas, pero antes
        # el número y la etiqueta de unidad mostrados no coincidían entre sí.
        db.execute("""INSERT INTO movimientos(producto_id,tipo,cantidad,motivo,evento_id,costo_unitario)
                      VALUES (?,'perdida',?,?,?,?)""",
                   (producto_id, cantidad, motivo, evento_id, costo_venta))
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
        bono = form_float("bono_rebelion", 0)
        if bono is None or bono < 0:
            flash("El Bono Rebelión debe ser un valor igual o mayor a cero.", "danger")
            return redirect(url_for("evento", evento_id=evento_id))
        db.execute("UPDATE eventos SET estado='cerrado', bono_rebelion=? WHERE id=?", (bono, evento_id))
        db.commit()
        flash("Evento cerrado. Se prepara el balance consolidado para imprimir.", "success")
        return redirect(url_for("ticket_evento", evento_id=evento_id) + "?auto=1")
    return redirect(url_for("evento", evento_id=evento_id))


# ================= AJUSTES Y VERSIONES =================

@app.route("/ajustes", methods=["GET", "POST"])
def ajustes():
    db = get_conn()
    if request.method == "POST":
        if request.form.get("accion") == "restablecer":
            db.execute("DELETE FROM config")
            db.commit()
            flash("Textos de los tickets restablecidos.", "success")
            return redirect(url_for("ajustes"))
        for clave, defecto in TICKET_DEFAULTS.items():
            valor = request.form.get(clave, "").strip()[:160]
            if valor and valor != defecto:
                db.execute("INSERT OR REPLACE INTO config(clave,valor) VALUES(?,?)", (clave, valor))
            else:
                db.execute("DELETE FROM config WHERE clave=?", (clave,))
        db.commit()
        flash("Textos de los tickets guardados.", "success")
        return redirect(url_for("ajustes"))
    return render_template("ajustes.html", textos=textos_ticket())


@app.route("/versiones")
def versiones():
    return render_template("versiones.html", cambios=CAMBIOS)


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
            round(m["cantidad"], 2), m["unidad"], m["motivo"] or "", m["evento"] or "-"
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
        SELECT p.nombre, p.unidad_venta AS unidad, m.cantidad,
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
    gastos_evento_export = db.execute(
        "SELECT COALESCE(SUM(monto),0) FROM gastos WHERE evento_id=?", (evento_id,)
    ).fetchone()[0]
    resultado = margen_ventas - total_perdidas - gastos_evento_export + (evento["bono_rebelion"] or 0)

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
    ws_ventas.append(["GASTOS ($)", gastos_evento_export])
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

    print(f"\nRebelión Stock v{VERSION} iniciado.")
    print("PC:       http://127.0.0.1:5000")
    for ip in local_ips:
        print(f"Red local: http://{ip}:5000")
    print("\nLas personas conectadas a la misma red pueden abrir la dirección 'Red local'.")
    print("Para detener el servidor: Ctrl+C\n")
    serve(app, host="0.0.0.0", port=5000, threads=8)
