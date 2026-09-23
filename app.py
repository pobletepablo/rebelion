from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from database import get_db, init_db
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import io
import datetime

app = Flask(__name__)
app.secret_key = "rebelion-clave-local"
init_db()

@app.template_filter("money")
def money(value):
    return f"${value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

@app.route("/")
def index():
    db = get_db()
    productos = db.execute("""
        SELECT *, CASE WHEN stock <= stock_minimo THEN 1 ELSE 0 END stock_bajo
        FROM productos WHERE activo=1 ORDER BY nombre
    """).fetchall()
    stock_bajo = [p for p in productos if p["stock_bajo"]]
    
    evento = db.execute("""
        SELECT * FROM eventos WHERE estado='abierto'
        ORDER BY fecha DESC, id DESC LIMIT 1
    """).fetchone()
    
    ventas_evento = margen_evento = 0
    if evento:
        ventas_evento = db.execute(
            "SELECT COALESCE(SUM(total),0) FROM ventas WHERE evento_id=?",
            (evento["id"],)).fetchone()[0]
        margen_evento = db.execute("""
            SELECT COALESCE(SUM(vi.cantidad*(vi.precio_unitario-vi.costo_unitario)),0)
            FROM venta_items vi JOIN ventas v ON v.id=vi.venta_id
            WHERE v.evento_id=?
        """, (evento["id"],)).fetchone()[0]
        
    valor_stock = sum(p["stock"] * p["costo"] for p in productos)
    total_unidades_stock = sum(p["stock"] for p in productos)
    
    # Obtener mes actual formato YYYY-MM
    mes_actual = datetime.datetime.now().strftime("%Y-%m")
    
    # Pérdidas del mes actual
    perdidas_mes = db.execute("""
        SELECT COALESCE(SUM(m.cantidad * p.costo), 0) as valor_perdida,
               COALESCE(SUM(m.cantidad), 0) as cant_perdida
        FROM movimientos m
        JOIN productos p ON p.id = m.producto_id
        WHERE m.tipo = 'perdida' AND strftime('%Y-%m', m.fecha_hora) = ?
    """, (mes_actual,)).fetchone()
    
    # Últimos 5 eventos
    ultimos_eventos = db.execute("""
        SELECT e.*, COALESCE(SUM(v.total), 0) as recaudacion
        FROM eventos e
        LEFT JOIN ventas v ON v.evento_id = e.id
        GROUP BY e.id
        ORDER BY e.fecha DESC, e.id DESC
        LIMIT 5
    """).fetchall()
    
    db.close()
    return render_template("index.html", productos=productos, stock_bajo=stock_bajo,
                           evento=evento, ventas_evento=ventas_evento,
                           margen_evento=margen_evento, valor_stock=valor_stock,
                           total_unidades_stock=total_unidades_stock,
                           perdidas_mes=perdidas_mes, ultimos_eventos=ultimos_eventos,
                           mes_actual=mes_actual)

@app.route("/productos")
def productos():
    db=get_db()
    productos=db.execute("SELECT * FROM productos WHERE activo=1 ORDER BY nombre").fetchall()
    db.close()
    return render_template("productos.html", productos=productos)

@app.route("/productos/nuevo", methods=["GET","POST"])
def nuevo_producto():
    if request.method=="POST":
        datos=(request.form["nombre"].strip(),request.form["categoria"],
               float(request.form["costo"]),float(request.form["precio"]),
               float(request.form["stock"]),float(request.form["stock_minimo"]),
               request.form["unidad"])
        db=get_db()
        cur=db.execute("""INSERT INTO productos
            (nombre,categoria,costo,precio,stock,stock_minimo,unidad)
            VALUES (?,?,?,?,?,?,?)""",datos)
        if datos[4]>0:
            db.execute("""INSERT INTO movimientos(producto_id,tipo,cantidad,motivo)
                          VALUES (?,'entrada',?,'Stock inicial')""",(cur.lastrowid,datos[4]))
        db.commit(); db.close()
        flash("Producto creado correctamente.","success")
        return redirect(url_for("productos"))
    return render_template("producto_form.html")

@app.route("/productos/<int:producto_id>/stock", methods=["POST"])
def modificar_stock(producto_id):
    cantidad=float(request.form["cantidad"]); tipo=request.form["tipo"]
    motivo=request.form.get("motivo","")
    db=get_db()
    p=db.execute("SELECT * FROM productos WHERE id=?",(producto_id,)).fetchone()
    if not p:
        db.close(); flash("Producto inexistente.","danger"); return redirect(url_for("productos"))
    
    if tipo=="entrada":
        nuevo=p["stock"]+cantidad
    elif tipo in ["salida", "perdida"]:
        nuevo=p["stock"]-cantidad
        if nuevo<0:
            db.close(); flash("No hay suficiente stock.","danger"); return redirect(url_for("productos"))
    else:
        nuevo=cantidad
        tipo="ajuste"
        
    db.execute("UPDATE productos SET stock=? WHERE id=?",(nuevo,producto_id))
    db.execute("""INSERT INTO movimientos(producto_id,tipo,cantidad,motivo)
                  VALUES (?,?,?,?)""",(producto_id,tipo,cantidad,motivo))
    db.commit(); db.close()
    
    msg = "Pérdida registrada correctamente." if tipo == "perdida" else "Stock actualizado."
    flash(msg, "warning" if tipo == "perdida" else "success")
    return redirect(url_for("productos"))

@app.route("/movimientos")
def movimientos():
    db = get_db()
    mes = request.args.get("mes", datetime.datetime.now().strftime("%Y-%m"))
    movs = db.execute("""
        SELECT m.*, p.nombre as producto_nombre, p.unidad, e.nombre as evento_nombre
        FROM movimientos m
        JOIN productos p ON p.id = m.producto_id
        LEFT JOIN eventos e ON e.id = m.evento_id
        WHERE strftime('%Y-%m', m.fecha_hora) = ?
        ORDER BY m.fecha_hora DESC, m.id DESC
    """, (mes,)).fetchall()
    db.close()
    return render_template("movimientos.html", movimientos=movs, mes=mes)

@app.route("/eventos")
def eventos():
    db=get_db()
    eventos=db.execute("""SELECT e.*,COALESCE(SUM(v.total),0) recaudacion
                          FROM eventos e LEFT JOIN ventas v ON v.evento_id=e.id
                          GROUP BY e.id ORDER BY e.fecha DESC,e.id DESC""").fetchall()
    db.close()
    return render_template("eventos.html",eventos=eventos)

@app.route("/eventos/nuevo",methods=["POST"])
def nuevo_evento():
    db=get_db()
    db.execute("INSERT INTO eventos(nombre,fecha,notas) VALUES(?,?,?)",
               (request.form["nombre"],request.form["fecha"],request.form.get("notas","")))
    db.commit(); db.close()
    flash("Evento creado.","success")
    return redirect(url_for("eventos"))

@app.route("/eventos/<int:evento_id>")
def evento(evento_id):
    db=get_db()
    evento=db.execute("SELECT * FROM eventos WHERE id=?",(evento_id,)).fetchone()
    if not evento: db.close(); return "Evento no encontrado",404
    ventas=db.execute("SELECT * FROM ventas WHERE evento_id=? ORDER BY id DESC",(evento_id,)).fetchall()
    pv=db.execute("""SELECT p.nombre,p.unidad,SUM(vi.cantidad) cantidad,
                     SUM(vi.cantidad*vi.precio_unitario) total,
                     SUM(vi.cantidad*(vi.precio_unitario-vi.costo_unitario)) margen
                     FROM venta_items vi JOIN ventas v ON v.id=vi.venta_id
                     JOIN productos p ON p.id=vi.producto_id
                     WHERE v.evento_id=? GROUP BY p.id ORDER BY total DESC""",(evento_id,)).fetchall()
    recaudacion=sum(v["total"] for v in ventas); margen=sum(p["margen"] for p in pv)
    db.close()
    return render_template("evento.html",evento=evento,ventas=ventas,
                           productos_vendidos=pv,recaudacion=recaudacion,margen=margen)

@app.route("/eventos/<int:evento_id>/venta",methods=["GET","POST"])
def nueva_venta(evento_id):
    db=get_db()
    evento=db.execute("SELECT * FROM eventos WHERE id=?",(evento_id,)).fetchone()
    if request.method=="POST":
        producto_id=int(request.form["producto_id"]); cantidad=float(request.form["cantidad"])
        medio=request.form["medio_pago"]
        p=db.execute("SELECT * FROM productos WHERE id=?",(producto_id,)).fetchone()
        if not p or cantidad<=0 or p["stock"]<cantidad:
            db.close(); flash("Producto inexistente, cantidad inválida o stock insuficiente.","danger")
            return redirect(request.url)
        total=cantidad*p["precio"]
        cur=db.execute("INSERT INTO ventas(evento_id,medio_pago,total) VALUES(?,?,?)",
                       (evento_id,medio,total))
        db.execute("""INSERT INTO venta_items
            (venta_id,producto_id,cantidad,costo_unitario,precio_unitario)
            VALUES(?,?,?,?,?)""",(cur.lastrowid,producto_id,cantidad,p["costo"],p["precio"]))
        db.execute("UPDATE productos SET stock=stock-? WHERE id=?",(cantidad,producto_id))
        db.execute("""INSERT INTO movimientos(producto_id,tipo,cantidad,motivo,evento_id)
                      VALUES (?,'venta',?,'Venta',?)""",(producto_id,cantidad,evento_id))
        db.commit(); db.close()
        flash("Venta registrada.","success")
        return redirect(url_for("evento",evento_id=evento_id))
    productos=db.execute("SELECT * FROM productos WHERE activo=1 ORDER BY nombre").fetchall()
    db.close()
    return render_template("venta.html",evento=evento,productos=productos)

@app.route("/eventos/<int:evento_id>/cerrar",methods=["POST"])
def cerrar_evento(evento_id):
    db=get_db(); db.execute("UPDATE eventos SET estado='cerrado' WHERE id=?",(evento_id,))
    db.commit(); db.close()
    flash("Evento cerrado.","success")
    return redirect(url_for("evento",evento_id=evento_id))

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
            cell = ws.cell(row=row, column=col)
            cell.border = border_light

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

@app.route("/exportar/movimientos")
def exportar_movimientos():
    mes = request.args.get("mes", datetime.datetime.now().strftime("%Y-%m"))
    db = get_db()
    movs = db.execute("""
        SELECT m.id, m.fecha_hora, p.nombre as producto, m.tipo, m.cantidad, p.unidad, m.motivo, e.nombre as evento
        FROM movimientos m
        JOIN productos p ON p.id = m.producto_id
        LEFT JOIN eventos e ON e.id = m.evento_id
        WHERE strftime('%Y-%m', m.fecha_hora) = ?
        ORDER BY m.fecha_hora ASC
    """, (mes,)).fetchall()
    db.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Movimientos {mes}"

    ws.append(["ID", "Fecha / Hora", "Producto", "Tipo", "Cantidad", "Unidad", "Motivo", "Evento"])
    for m in movs:
        ws.append([
            m["id"],
            m["fecha_hora"],
            m["producto"],
            m["tipo"].capitalize(),
            m["cantidad"],
            m["unidad"],
            m["motivo"] or "",
            m["evento"] or "-"
        ])

    _estilar_excel(ws, f"MOVIMIENTOS DEL MES ({mes})")

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"movimientos_{mes}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/exportar/evento/<int:evento_id>")
def exportar_evento(evento_id):
    db = get_db()
    evento = db.execute("SELECT * FROM eventos WHERE id=?", (evento_id,)).fetchone()
    if not evento:
        db.close()
        return "Evento no encontrado", 404

    ventas = db.execute("""
        SELECT v.id, v.fecha_hora, v.medio_pago, v.total
        FROM ventas v
        WHERE v.evento_id=?
        ORDER BY v.id ASC
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

    db.close()

    wb = openpyxl.Workbook()
    ws_prod = wb.active
    ws_prod.title = "Resumen por Producto"
    ws_prod.append(["Producto", "Categoría", "Cantidad Vendida", "Unidad", "Total Recaudado ($)", "Margen ($)"])

    for p in pv:
        ws_prod.append([
            p["nombre"],
            p["categoria"],
            p["cantidad"],
            p["unidad"],
            p["total"],
            p["margen"]
        ])
    
    _estilar_excel(ws_prod, f"RESUMEN EVENTO - {evento['nombre']} ({evento['fecha']})")

    ws_ventas = wb.create_sheet(title="Detalle de Ventas")
    ws_ventas.append(["ID Venta", "Fecha / Hora", "Medio de Pago", "Total ($)"])
    for v in ventas:
        ws_ventas.append([
            v["id"],
            v["fecha_hora"],
            v["medio_pago"].capitalize(),
            v["total"]
        ])
    _estilar_excel(ws_ventas, f"DETALLE DE VENTAS - {evento['nombre']}")

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    nombre_limpio = "".join(c if c.isalnum() else "_" for c in evento["nombre"])
    filename = f"evento_{evento_id}_{nombre_limpio}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=5000,debug=True)
