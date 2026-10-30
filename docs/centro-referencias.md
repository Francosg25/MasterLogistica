# Centro de referencias

El espacio de trabajo organiza la operación por referencia y responsable. El documento de nomenclatura, versión 01 del 8 de octubre de 2026, define sus procesos, códigos, BU y movimientos derivados. Los cinco masters de Logística conservan sus columnas de origen. Compliance utiliza una vista común de operación; no se inventan columnas de un Excel no suministrado.

## Recorrido de trabajo

- **Inicio:** información real del alcance autorizado: referencias activas, provisiones vivas, facturas del mes, saldos separados por moneda y referencias recientes. La demostración identifica sus datos como ficticios.
- **Referencias:** selección de master de Logística o Compliance y edición directa de celdas. La selección anterior se recuerda por usuario, siempre que siga autorizada. Los registros mantienen la mayor parte del espacio.
- **Consolidar:** acceso directo al archivo de facturación, detección de meses y referencias, revisión de excepciones y una acción para confirmar las listas. Se mantienen los controles de duplicidad y la evidencia original.
- **Provisiones:** alta con aprobación automática y saldos vivos, parcialmente aplicados o liquidados. Los pendientes continúan en meses siguientes.
- **Facturas:** importes registrados, aplicados y pendientes; cada referencia se ve directamente en la tabla.
- **Reporte mensual:** estado histórico al cierre y aplicaciones del mes con factura, fecha, importe, saldo y moneda. Descarga CSV para Excel.
- **Historial:** usuario, fecha, movimiento y valores anteriores y nuevos.

**Ctrl + K** busca una referencia actual o un alias registrado y abre su ficha. La ficha separa operación, provisiones/facturas e historial. Desde ella se puede iniciar una provisión o factura con la referencia ya capturada.

## Referencias madre y movimientos

Cada movimiento nuevo conserva un `parent_shipment_id` explícito y un `movement_number` único dentro de su madre. El servidor asigna `.1`, `.2`, etc., en una transacción que bloquea la madre. Se reservan también los números encontrados en referencias y alias históricos. Crear simultáneamente varios movimientos no debe repetir números. Cada fila tiene además su SEC de master, independiente del número del movimiento.

El vínculo utiliza el ID de la operación. Corregir el texto de la madre no desprende a sus movimientos ya vinculados. Cada movimiento conserva su propio ID, proveedor, provisiones, facturas y aplicaciones: visualizar una familia no combina sus cuentas ni liquida saldos de otro movimiento.

Las referencias numéricas históricas pueden aparecer en la familia cuando su base coincide exactamente y pertenecen a la misma empresa y al alcance autorizado. Esta asociación de lectura no reescribe datos ni reasigna facturas. Los distintivos DMR/PFA/CS se reconocen como tales; no se convierten en nuevos movimientos numerados por el hecho de llevar un distintivo.

El número base identifica al dueño original según la nomenclatura. Administración puede asignar el movimiento a otro master autorizado, por ejemplo transporte relacionado con una madre de Compliance. El nuevo número conserva la clasificación y empresa de la madre. Los permisos de acceso existentes se siguen aplicando en el servidor.

## Catálogos

BU: M00 (varias BU), M01 (BM), M19 (PC), M20 (BC), M23 (ETM), M45 (IPG), M46 (AS), M65 (IPG).

Procesos: RM, AF, FG, CR, FA. Operaciones: AE, AI, SE, SI, LI, LE, PI, PE, VI, VE, A3, F4, F5, R1. Los analistas 1–5 conservan sus masters; 6–8 utilizan la vista común de Compliance. El código 9 continúa sin preset. Los registros históricos y el departamento sin asignar siguen admitidos.

## Datos y actualización

SQLite local: esquema 7, con ampliación aditiva del esquema 6. PostgreSQL: migración `0011_reference_families` posterior a `0010_automatic_sec`. Se agregan vínculos y restricciones; no se borran ni se renumeran referencias ni movimientos financieros. Las cuentas adicionales de Compliance se crean exclusivamente en la base de desarrollo local; no se crean cuentas corporativas ni se conceden permisos de Entra.

## Alcance de la automatización

Se automatizan el consecutivo, la numeración de movimientos, la búsqueda de referencias y alias, la identificación de meses, la detección de duplicados, la aplicación a provisiones compatibles, el arrastre y los cálculos del reporte. Las excepciones que no tienen información suficiente permanecen visibles para revisión; el sistema no inventa referencias, repartos ni tipos de cambio.

La lectura directa de facturas PDF/XML y la carga masiva de los cinco masters históricos requieren sus flujos específicos. Esta versión conserva la importación del consolidado XLSX y la edición/captura de masters. No anuncia ejecución desatendida de procesos que aún no están implementados.
