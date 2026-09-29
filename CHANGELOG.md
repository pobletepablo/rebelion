
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
