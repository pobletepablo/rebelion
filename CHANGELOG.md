
## V3.1 — Responsables y Agenda

### Eventos
- Cada evento nuevo requiere al menos un responsable.
- Grilla de responsables con rol `General`, `Caja` o `Cocina`.
- Turnos configurables con hora de inicio y fin.
- Se pueden agregar y quitar responsables desde el detalle del evento.
- Se mantiene el bono fuera de la creación y se registra únicamente al cerrar el evento.

### Agenda
- Nueva pestaña **Agenda** para actividades futuras y reservas del local.
- Calendario mensual con actividades por día.
- Tipos: Actividad, Reserva, Reunión y Otro.
- Horarios opcionales de inicio y fin.
- Listado de próximas actividades con posibilidad de eliminarlas.
- Resumen de próximas actividades visible también en el Dashboard.

### Dashboard
- Se mantiene el foco cotidiano en Caja y Gastos.
- Se eliminó el detalle de recaudación del panel principal del evento para llevarlo a la vista específica del evento.
- El panel derecho prioriza el evento vigente o, si no existe, los últimos eventos.
- Se incorporó el acceso a la Agenda y sus próximas actividades.

### Ticket
- El encabezado de ticket queda únicamente con el logo de Rebelión y `@rebelion.lp`; se elimina el texto "Casa Socialista".

# Changelog — Rebelión Stock V3

## V3.0.1 — Corrección de disponibilidad libre

- Corregida la alerta de stock bajo: los productos configurados como **Disponibilidad libre** ya no aparecen como stock bajo aunque su stock interno sea 0.
- El stock mínimo deja de tener efecto para productos de disponibilidad libre.
- En el formulario de producto, el campo de stock mínimo se oculta al seleccionar Disponibilidad libre.
- Al guardar un producto libre, el sistema fuerza `stock_minimo = 0` para evitar conflictos posteriores.

# Changelog — Rebelión Stock

## [3.0.0] — 2026-09-27

### Eventos y Bono Rebelión
- Se eliminó el campo **Bono Rebelión** de la creación de eventos.
- El bono ahora se registra únicamente cuando el evento está **cerrado**.
- El detalle del evento indica claramente que el bono corresponde al cierre.
- El cálculo del resultado del evento ahora contempla:
  - margen de las ventas;
  - pérdidas de stock;
  - gastos asociados al evento;
  - Bono Rebelión.
- Se mantiene la separación entre **Caja** y **Ganancia neta**.

### Bebidas por rendimiento
- Se incorporó el concepto de **unidad de stock** y **unidad de venta**.
- Cada producto puede tener un **rendimiento configurable**.
- Ejemplo: 1 botella de fernet → 20 vasos.
- El stock se descuenta proporcionalmente: vender 5 vasos consume 0,25 botella.
- El costo de cada vaso se calcula automáticamente a partir del costo de la botella y su rendimiento.
- La venta se limita a la disponibilidad calculada de vasos.
- El rendimiento es configurable por producto, por lo que sirve para distintas bebidas y tamaños.

### Comidas / productos sin cantidad exacta
- Se agregó **Disponibilidad libre**.
- Permite registrar ventas sin cargar un stock inicial exacto.
- Es útil para productos preparados en cantidad variable, como **sanguches de bondiola**.
- El sistema registra cuántos se vendieron durante el evento, pero no inventa ni exige una cantidad de producción.

### Stock y movimientos
- Los movimientos de inventario distinguen entre unidad física de stock y unidad de venta.
- Los movimientos de ventas y pérdidas se muestran en la unidad de venta cuando corresponde.
- Los movimientos de entrada/salida/ajuste se mantienen en la unidad física de stock.
- Se mantienen las compatibilidades con productos creados en V2 mediante migración automática de la base SQLite.

### Dashboard y reportes
- **Ganancia neta** ahora descuenta gastos además de costos y pérdidas, y suma el bono.
- **Caja disponible** continúa representando dinero: ventas + bonos − gastos.
- Exportaciones de movimientos y eventos fueron adaptadas a productos con rendimiento.

### Compatibilidad
- Las bases de datos existentes de V2 se migran automáticamente al iniciar V3.
- Los productos existentes quedan inicialmente como **Stock exacto**, conservando sus unidades y valores.
- No se eliminan ventas, eventos, gastos ni movimientos históricos.

## [2.x]
Versión anterior del sistema con:
- Gestión de stock.
- Eventos.
- Registro de ventas.
- Pérdidas.
- Caja y gastos.
- Bono Rebelión.
- Exportaciones a Excel.
- Servidor Waitress.

## [3.1.0] — 2026-09-27

### Dashboard
- Se simplificó el Dashboard principal para mostrar únicamente la información financiera cotidiana: **Caja disponible** y **Gastos**.
- Se retiraron del Dashboard los detalles de recaudación, bonos, pérdidas, ganancias y métricas de stock.
- La información detallada queda concentrada dentro de cada evento, donde tiene mayor utilidad operativa.
- Nuevo diseño en dos columnas: información financiera a la izquierda y actividad de eventos a la derecha.
- Si existe un evento vigente, se muestra primero con acceso directo al evento.
- Si no existe un evento vigente, se muestran los últimos eventos registrados.

### Registro de ventas
- Después de registrar una venta, el sistema vuelve automáticamente a **Registrar venta** del mismo evento.
- Esto permite cargar ventas consecutivas sin volver al detalle del evento entre operación y operación.
- Se mejoró la alineación de producto, cantidad, total y botón de eliminación.
- Los controles de cantidad y selección de producto tienen alturas consistentes.
- La vista móvil reorganiza los controles para facilitar la carga desde un teléfono.

### Experiencia móvil
- Se reforzó el diseño responsive del Dashboard y de la pantalla de ventas.
- Se priorizaron botones y controles táctiles con dimensiones consistentes.
- El detalle del evento continúa concentrando la información operativa y financiera específica del evento.

## V3.1.1 — Estética real de marca + corrección de bugs

### Estética
- Paleta de colores reemplazada por la del perfil de marca real (carbón #2B2B2C, coral, teal, mostaza) en vez de rojo/negro genérico.
- Logo reemplazado por el isotipo real extraído del perfil de marca, con fondo transparente.
- Tipografía de títulos: Anton (OFL, autohospedada en static/fonts/, no depende de internet) en vez de una condensada genérica.
- Detalle decorativo de "estrella" en el hero del dashboard, inspirado en los destellos del perfil de marca.
- Medios de pago (Efectivo/Transferencia) y tipos de agenda recoloreados con teal/mostaza en vez de verde/azul genéricos.

### Bugs corregidos
- Dashboard: "ganancias_local" no restaba los gastos totales por un error de orden de evaluación (`locals()` se consultaba antes de asignar la variable). No era visible en el dashboard actual (la variable no se renderiza en ningún template de esta versión) pero quedaba mal calculada.
- Ventas de productos de disponibilidad libre no generaban ningún registro en `movimientos`: no aparecían en /movimientos ni en su exportación a Excel (sí se contaban bien en los totales del evento, que usan venta_items).
- Ventas y pérdidas de productos con rendimiento (ej: fernet por vaso) registraban la cantidad en la unidad de stock (fracción de botella) pero la pantalla la etiquetaba como unidad de venta (vaso), mostrando números como "0,21 vaso" en vez de "3 vaso". El costo unitario tampoco se dividía por el rendimiento en ese registro.
- La exportación a Excel del evento no restaba los gastos del "Resultado del evento", a diferencia de la pantalla del evento, que sí los restaba — dos números distintos para el mismo evento.
- Cantidades en la exportación de movimientos ya se redondean a 2 decimales en vez de mostrar floats largos.

## V3.3 - Ajustes de operación
- Balance de actividad imprimible en formato ticket de 80 mm.
- Gastos incorporados directamente dentro de cada evento.
- Se elimina Caja del menú principal; los gastos y el balance se gestionan desde Evento.
- Venta rápida con botones/iconos de productos en lugar de lista desplegable.
- Acceso simple: cualquier nombre puede entrar como invitado; la contraseña fija 1917 da acceso de administrador.


## V3.3.1 — Fotos de productos en ventas
- Se puede cargar una foto JPG, PNG o WEBP al crear o editar un producto (máximo 5 MB).
- Las fotos se muestran en las tarjetas de productos de la pantalla de venta; los productos sin foto conservan su ícono por categoría.
- Se puede reemplazar o quitar la foto desde la edición del producto.
- La base de datos incorpora una migración automática para el campo de imagen.


## V3.4 — Modo Evento y tickets
- Invitados: redirección automática al Modo Evento cuando existe un evento vigente; el administrador conserva el Dashboard completo.
- Modo Evento con accesos rápidos a ventas, consulta de stock, agenda y responsables.
- Selector de tema claro/oscuro con preferencia guardada en el navegador.
- TPV: opción persistente para imprimir automáticamente el comprobante individual de cada venta.
- Cierre de evento: carga del Bono Rebelión en el mismo paso y apertura automática del balance consolidado para imprimir.
- Tickets con el logo gráfico de Rebelión; el balance agrupa las ventas por producto y muestra totales de recaudación, medios de pago, gastos, pérdidas y balance final.
