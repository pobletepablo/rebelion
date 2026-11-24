"""Historial de versiones. Fuente única: se muestra en /versiones.
Agregar cada versión nueva ARRIBA de la lista. CHANGELOG.md es una copia legible."""

VERSION = "3.5.0"

CAMBIOS = [
    {
        "version": "3.5.0", "fecha": "2026-11-24", "titulo": "Pulido, móvil y tickets editables",
        "cambios": [
            "Nueva pantalla Versiones con el historial completo.",
            "Nueva pantalla Ajustes (admin): se editan los textos de los tickets y se restablecen a los originales.",
            "Tickets con el logo negro «Rebelión · Casa Socialista» (antes se veía blanco sobre blanco) y hoja de impresión de 80 mm.",
            "Móvil: las tablas pasan a tarjetas, así Editar y Eliminar en Stock ya no quedan cortados.",
            "Móvil: campos de fecha, hora y selectores con el mismo alto y sin desbordes; calendario con puntos.",
            "Móvil: fotos de hasta 10 MB, con aviso claro si se pasan.",
            "Evento: se corrigió la estructura rota de la página (sección de gastos duplicada y sin cerrar).",
            "Evento: los gastos se pueden eliminar desde el propio evento (admin).",
            "Venta: productos sin stock deshabilitados, no se envía una venta vacía y el botón no se puede tocar dos veces.",
            "Venta: nombres con comillas o símbolos ya no rompen la pantalla.",
            "Ticket de venta: botón para volver directo a Registrar venta.",
            "Pérdidas manuales de productos con rendimiento: ahora se muestran en la unidad de venta, igual que las del evento.",
            "Excel del evento: unidad correcta en pérdidas y gastos incluidos en el desglose.",
            "Contraseña de administrador incorrecta: ahora avisa en vez de entrar como invitado.",
            "La sesión sobrevive a reinicios del servidor; el tipo de letra se incluye en la app (funciona sin internet).",
            "Textos simplificados en todas las pantallas y estilos unificados (CSS ordenado, modo claro por variables).",
        ],
    },
    {
        "version": "3.4.4", "fecha": "", "titulo": "Cabecera compacta e impresión",
        "cambios": [
            "Cabecera compacta en el celular.",
            "Botón de impresión automática con estado visible (verde/rojo).",
        ],
    },
    {
        "version": "3.4.3", "fecha": "", "titulo": "Modo claro",
        "cambios": ["Modo claro con contraste real en tarjetas, formularios, botones y alertas."],
    },
    {
        "version": "3.4.2", "fecha": "", "titulo": "Adaptación móvil",
        "cambios": [
            "Venta táctil: catálogo de dos columnas, controles amplios y barra de pago fija abajo.",
            "Navegación y cabecera adaptadas a pantallas chicas.",
        ],
    },
    {
        "version": "3.4.0", "fecha": "", "titulo": "Modo Evento y tickets",
        "cambios": [
            "Los invitados entran directo a la venta cuando hay un evento vigente; el administrador conserva el Dashboard.",
            "Tema claro/oscuro con preferencia guardada en el navegador.",
            "Opción persistente para imprimir automáticamente el comprobante de cada venta.",
            "Cierre de evento con Bono Rebelión en el mismo paso y balance consolidado listo para imprimir.",
            "Tickets con el logo de Rebelión; el balance agrupa las ventas por producto.",
        ],
    },
    {
        "version": "3.3.1", "fecha": "", "titulo": "Fotos de productos",
        "cambios": [
            "Foto JPG, PNG o WEBP al crear o editar un producto; se muestra en las tarjetas de venta.",
            "Migración automática de la base para el campo de imagen.",
        ],
    },
    {
        "version": "3.3.0", "fecha": "", "titulo": "Ajustes de operación",
        "cambios": [
            "Balance de actividad imprimible en formato ticket de 80 mm.",
            "Gastos dentro de cada evento; Caja sale del menú.",
            "Venta rápida con botones de producto en lugar de lista desplegable.",
            "Acceso simple: cualquier nombre entra como invitado; la contraseña de administrador da acceso completo.",
        ],
    },
    {
        "version": "3.1.1", "fecha": "", "titulo": "Estética de marca",
        "cambios": [
            "Paleta, logo y tipografía de la marca real.",
            "Corregido el cálculo de ganancias del local, que no restaba gastos.",
            "Las ventas de disponibilidad libre ahora generan movimiento y aparecen en la exportación.",
            "Ventas y pérdidas con rendimiento se registran en la unidad de venta (ej.: 3 vasos y no 0,15 botella).",
            "El Excel del evento ahora resta los gastos, igual que la pantalla.",
        ],
    },
    {
        "version": "3.1.0", "fecha": "2026-09-27", "titulo": "Dashboard, ventas, responsables y agenda",
        "cambios": [
            "Dashboard simplificado: Caja disponible, Gastos y actividad de eventos.",
            "Después de una venta se vuelve a Registrar venta para cargar en cadena.",
            "Cada evento requiere al menos un responsable (General, Caja o Cocina) con turnos.",
            "Nueva Agenda con calendario mensual y próximas actividades.",
        ],
    },
    {
        "version": "3.0.1", "fecha": "", "titulo": "Corrección de disponibilidad libre",
        "cambios": ["Los productos de disponibilidad libre ya no aparecen con stock bajo."],
    },
    {
        "version": "3.0.0", "fecha": "2026-09-27", "titulo": "Rendimiento y disponibilidad libre",
        "cambios": [
            "El Bono Rebelión se carga únicamente al cerrar el evento.",
            "Unidad de stock y de venta con rendimiento (1 botella de fernet = 20 vasos).",
            "Disponibilidad libre para productos sin cantidad exacta (ej.: sanguches de bondiola).",
            "Ganancia neta = margen − pérdidas − gastos + bono. Caja = ventas + bonos − gastos.",
            "Las bases de V2 se migran solas al iniciar.",
        ],
    },
    {
        "version": "2.x", "fecha": "", "titulo": "Base del sistema",
        "cambios": [
            "Stock, eventos, ventas, pérdidas, caja y gastos, Bono Rebelión.",
            "Exportaciones a Excel y servidor Waitress.",
        ],
    },
]


def a_markdown():
    out = ["# Historial de versiones — Rebelión Stock\n"]
    for c in CAMBIOS:
        fecha = f" — {c['fecha']}" if c["fecha"] else ""
        out.append(f"## {c['version']}{fecha} · {c['titulo']}")
        out.extend(f"- {x}" for x in c["cambios"])
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    print(a_markdown())
