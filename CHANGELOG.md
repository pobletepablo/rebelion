# Historial de versiones — Rebelión Stock

## 3.5.0 — 2026-11-24 · Pulido, móvil y tickets editables
- Nueva pantalla Versiones con el historial completo.
- Nueva pantalla Ajustes (admin): se editan los textos de los tickets y se restablecen a los originales.
- Tickets con el logo negro «Rebelión · Casa Socialista» (antes se veía blanco sobre blanco) y hoja de impresión de 80 mm.
- Móvil: las tablas pasan a tarjetas, así Editar y Eliminar en Stock ya no quedan cortados.
- Móvil: campos de fecha, hora y selectores con el mismo alto y sin desbordes; calendario con puntos.
- Móvil: fotos de hasta 10 MB, con aviso claro si se pasan.
- Evento: se corrigió la estructura rota de la página (sección de gastos duplicada y sin cerrar).
- Evento: los gastos se pueden eliminar desde el propio evento (admin).
- Venta: productos sin stock deshabilitados, no se envía una venta vacía y el botón no se puede tocar dos veces.
- Venta: nombres con comillas o símbolos ya no rompen la pantalla.
- Ticket de venta: botón para volver directo a Registrar venta.
- Pérdidas manuales de productos con rendimiento: ahora se muestran en la unidad de venta, igual que las del evento.
- Excel del evento: unidad correcta en pérdidas y gastos incluidos en el desglose.
- Contraseña de administrador incorrecta: ahora avisa en vez de entrar como invitado.
- La sesión sobrevive a reinicios del servidor; el tipo de letra se incluye en la app (funciona sin internet).
- Textos simplificados en todas las pantallas y estilos unificados (CSS ordenado, modo claro por variables).

## 3.4.4 · Cabecera compacta e impresión
- Cabecera compacta en el celular.
- Botón de impresión automática con estado visible (verde/rojo).

## 3.4.3 · Modo claro
- Modo claro con contraste real en tarjetas, formularios, botones y alertas.

## 3.4.2 · Adaptación móvil
- Venta táctil: catálogo de dos columnas, controles amplios y barra de pago fija abajo.
- Navegación y cabecera adaptadas a pantallas chicas.

## 3.4.0 · Modo Evento y tickets
- Los invitados entran directo a la venta cuando hay un evento vigente; el administrador conserva el Dashboard.
- Tema claro/oscuro con preferencia guardada en el navegador.
- Opción persistente para imprimir automáticamente el comprobante de cada venta.
- Cierre de evento con Bono Rebelión en el mismo paso y balance consolidado listo para imprimir.
- Tickets con el logo de Rebelión; el balance agrupa las ventas por producto.

## 3.3.1 · Fotos de productos
- Foto JPG, PNG o WEBP al crear o editar un producto; se muestra en las tarjetas de venta.
- Migración automática de la base para el campo de imagen.

## 3.3.0 · Ajustes de operación
- Balance de actividad imprimible en formato ticket de 80 mm.
- Gastos dentro de cada evento; Caja sale del menú.
- Venta rápida con botones de producto en lugar de lista desplegable.
- Acceso simple: cualquier nombre entra como invitado; la contraseña de administrador da acceso completo.

## 3.1.1 · Estética de marca
- Paleta, logo y tipografía de la marca real.
- Corregido el cálculo de ganancias del local, que no restaba gastos.
- Las ventas de disponibilidad libre ahora generan movimiento y aparecen en la exportación.
- Ventas y pérdidas con rendimiento se registran en la unidad de venta (ej.: 3 vasos y no 0,15 botella).
- El Excel del evento ahora resta los gastos, igual que la pantalla.

## 3.1.0 — 2026-09-27 · Dashboard, ventas, responsables y agenda
- Dashboard simplificado: Caja disponible, Gastos y actividad de eventos.
- Después de una venta se vuelve a Registrar venta para cargar en cadena.
- Cada evento requiere al menos un responsable (General, Caja o Cocina) con turnos.
- Nueva Agenda con calendario mensual y próximas actividades.

## 3.0.1 · Corrección de disponibilidad libre
- Los productos de disponibilidad libre ya no aparecen con stock bajo.

## 3.0.0 — 2026-09-27 · Rendimiento y disponibilidad libre
- El Bono Rebelión se carga únicamente al cerrar el evento.
- Unidad de stock y de venta con rendimiento (1 botella de fernet = 20 vasos).
- Disponibilidad libre para productos sin cantidad exacta (ej.: sanguches de bondiola).
- Ganancia neta = margen − pérdidas − gastos + bono. Caja = ventas + bonos − gastos.
- Las bases de V2 se migran solas al iniciar.

## 2.x · Base del sistema
- Stock, eventos, ventas, pérdidas, caja y gastos, Bono Rebelión.
- Exportaciones a Excel y servidor Waitress.

