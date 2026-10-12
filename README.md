# MasterLogistica

Aplicación de control de embarques. Incluye backend FastAPI/PostgreSQL y el primer bloque de Masters en Angular 21: acceso Microsoft, consulta, filtros, alta, edición y documentos por operación.

## Estado

- Referencias: nomenclatura versionada y catálogo de BU configurable.
- Masters: selección obligatoria de responsable y tipo de operación; búsqueda, paginación e indicadores limitados al master seleccionado. Los cinco integrantes de logística conservan masters individuales.
- Detalle: edición con control de concurrencia, pedimentos, BL, contenedores, guías y seguimiento de incidencias.
- Demostración: disponible sin credenciales, con datos ficticios y sólo lectura. No consulta ni modifica registros operativos.
- Finanzas: provisiones por referencia, aprobación, conciliación de facturas con varias referencias, arrastre mensual, cancelación con reversión y reporte CSV.
- Historial: usuario, fecha, acción, referencia y valores anteriores/nuevos; filtros y registros inmutables.
- Pendiente: importación automática de Excel/PDF/XML, cierre contable bloqueado y validación en PostgreSQL nativo, Docker y Microsoft Entra ID real.

## Arranque con Docker

Requisitos: Docker Desktop con Compose v2. Para generar la configuración inicial, Python 3.11+.

Desde la carpeta del repositorio, sólo en la primera instalación:

```powershell
py -3.13 scripts/configure_local.py
```

Si ya existe `.env`, conserva ese archivo y sus contraseñas. El script no lo sobrescribe.

Para construir e iniciar los servicios:

```powershell
docker compose up --build -d
```

Abre **http://127.0.0.1:4200**. Puedes seleccionar **Ver demostración** para revisar la interfaz. Documentación de la API en desarrollo: http://127.0.0.1:8000/docs.

Para revisar el estado:

```powershell
docker compose ps
```

## Frontend sin Docker

Requiere Node compatible con Angular 21: `^20.19.0`, `^22.12.0` o `^24.0.0`. Node **24.13.1** está dentro de ese rango.

```powershell
cd frontend
npm.cmd ci
npm.cmd start
```

Abre **http://127.0.0.1:4200**. Las llamadas `/api` se dirigen a `127.0.0.1:8000`. La demostración funciona aunque el backend no esté iniciado. Si ya tienes el servicio `web` de Docker usando el puerto 4200, detenlo con `docker compose stop web` desde la raíz antes de iniciar Angular.

## Configuración de acceso y catálogos

La aplicación necesita dos registros de Entra: API y SPA. En `.env`, configura `ENTRA_TENANT_ID`, `ENTRA_API_CLIENT_ID`, `ENTRA_FRONTEND_CLIENT_ID` y `ENTRA_ALLOWED_CLIENT_IDS` (arreglo JSON que incluya el ID de la SPA). La API espera tokens v2 y el permiso delegado `access_as_user`.

Registra **http://127.0.0.1:4200/** como URI de redirección de tipo **Single-page application**. Si usas `localhost`, registra también **http://localhost:4200/**. La URL debe coincidir con la que abras. La SPA no usa secretos de cliente.

`COMPANY_CODES` contiene las empresas permitidas. El catálogo privado de BU se carga desde un JSON con códigos y descripciones, por ejemplo `{"T01":"Unidad de ejemplo"}`:

```powershell
py -3.13 scripts/configure_business_units.py ruta\catalogo.business-units.json
docker compose up -d --force-recreate api
```

Mantén los catálogos reales fuera de Git. El administrador inicial se aprovisiona con el comando `python -m app.cli` utilizando las credenciales del proceso de migración. Por ejemplo, desde la raíz, sustituyendo los valores de ejemplo por la identidad aprobada:

```powershell
docker compose run --rm migrate python -m app.cli "OBJECT-ID-DEL-USUARIO" "admin@example.com" "Administrador"
```

Los demás usuarios y proveedores se administran mediante los endpoints de Fase 2. Un usuario necesita un código de analista y un contador inicial verificado para crear referencias. No asignes códigos ni consecutivos sin contrastarlos con el registro operativo existente.

## Roles y separación de masters

El acceso requiere una identidad Microsoft Entra válida y un usuario local activo, aprovisionado por administración. El rol se toma de la base de datos; no se elige al iniciar sesión ni se acepta desde el navegador.

| Rol | Consulta de masters | Modificación de datos operativos |
| --- | --- | --- |
| Operaciones (`OPERATOR`) | Su propio master, separado por operación | Alta y edición de registros propios |
| Gerencia (`MANAGER`) | Puede seleccionar responsables, uno por vez | Sólo lectura |
| Finanzas (`FINANCE`) | Registros propios según el alcance actual | Sin alta ni edición operativa; los permisos de provisiones se gestionan por separado |
| Super Admin (`SUPER_ADMIN`) | Puede seleccionar responsables, uno por vez | Edición y administración de usuarios; la captura desde esta interfaz se habilita sólo en su propio master |

La interfaz no carga embarques hasta seleccionar un master. Las rutas `/masters/shipments` y `/masters/summary` exigen `owner_id` y un único `operation_code`; la API rechaza el acceso a otro responsable para roles sin permiso de consulta transversal. Cambiar el responsable o la operación limpia los resultados y cierra el detalle anterior. La captura conserva el tipo de operación seleccionado y el servidor asigna el dueño autenticado.

Los códigos de analista 1–5 identifican a los integrantes de logística en el catálogo. Las cinco identidades de la demostración son ficticias; las cuentas reales deben aprovisionarse con sus códigos verificados. Los endpoints generales de embarques mantienen la consulta consolidada autorizada para Gerencia y Super Admin.

## Verificación

Frontend:

```powershell
cd frontend
npm.cmd run build
npx.cmd playwright install chromium
npm.cmd test
```

Verificación de la interfaz de hoja de cálculo: **31 pruebas de navegador aprobadas** y build de producción correcto. La ejecución local general del backend registró **166 pruebas aprobadas y 31 pruebas de integración pendientes de PostgreSQL nativo**. Los casos financieros también se comprobaron por separado en PGlite, con los límites descritos abajo.

Las pruebas de Masters usan un punto de entrada exclusivo de pruebas y respuestas simuladas. La prueba de acceso comprueba el bundle de producción y la demostración con el proveedor de autenticación real, sin iniciar sesión contra Microsoft. El build normal y el Dockerfile no incluyen el proveedor de pruebas.

Backend:

```powershell
python -m pip install --require-hashes -r backend/requirements-test.lock
cd backend
python -m pytest -q
```

Las pruebas de integración requieren una base PostgreSQL desechable cuyo nombre termine en `_test`, con `TEST_DATABASE_URL` y `TEST_ADMIN_DATABASE_URL` separados. Su preparación elimina el esquema de esa base de pruebas. Nunca uses una base operativa.

El arranque de contenedores y el SSO real deben verificarse antes del piloto. Los workflows de GitHub Actions están preparados, pero su ejecución depende de que la cuenta permita iniciar runners.

## Vista de demostración

La interfaz usa una hoja de cálculo como área principal: fondo blanco, tipografía del sistema, encabezados fijos, referencia fija en escritorio y columnas separadas para cada dato. No carga registros hasta abrir un master con un responsable y una operación. La demostración sigue siendo de solo lectura.

## Edición del master

- Doble clic, Enter, F2 o **Editar celda** abre la celda seleccionada. Tab y Enter confirman la edición y avanzan; Escape cancela la edición actual. Las flechas cambian de celda.
- Shift con flechas o clic selecciona un rango. Ctrl+C copia el rango; Ctrl+V pega desde Excel. Las fechas aceptan `dd/mm/aaaa` o `aaaa-mm-dd`. Los estados y proveedores se validan contra sus catálogos. Un rango inválido se rechaza completo.
- **Guardar cambios** o Ctrl+S envía los cambios pendientes. **Deshacer** o Ctrl+Z revierte ediciones aún no guardadas; **Descartar** elimina los cambios pendientes tras confirmar. Salir, cambiar de master, filtrar o cambiar de página solicita confirmar si hay ediciones pendientes.
- Cada fila se guarda con control de versión. Si una fila falla, se conservan sus cambios y los de las filas aún no enviadas. Los conflictos y los guardados sin confirmación requieren **Recargar fila** antes de volver a editar esa fila. El conjunto de filas no es una transacción única.
- Referencia y BU están protegidas porque forman parte de la identidad de la operación. El responsable y el tipo de operación permanecen fijados por el master. La edición respeta los roles del servidor.
- **Nuevo embarque** genera la referencia mediante el servidor. Abrir una referencia permite consultar o editar su detalle, incidencias y documentos.
- **Exportar página CSV** descarga las filas de la página visible, incluidos los cambios pendientes; no exporta el master completo ni un archivo XLSX. Se neutralizan valores que Excel podría interpretar como fórmulas. No se implementa cálculo de fórmulas ni importación de libros completos.

Los registros modificados permanecen visibles hasta actualizar o volver a aplicar los filtros.

![Masters con datos ficticios](frontend/docs/masters-preview.png)

## Provisiones, facturas e historial

El menú principal incorpora **Provisiones**, **Facturas y conciliación** e **Historial**. La demostración incluye ejemplos financieros ficticios de octubre de 2026 y continúa siendo de solo lectura.

### Flujo financiero

1. Finanzas o Administración selecciona un mes y pulsa **Abrir periodo**. Esto crea un periodo abierto; no cierra ni reemplaza otros meses.
2. En **Provisiones**, captura referencia existente, proveedor, concepto, línea de costo, mes de origen, moneda, importe neto y cargos extra. Guarda el borrador y pulsa **Aprobar**. Los borradores no afectan los saldos.
3. En **Facturas y conciliación**, registra folio, proveedor, empresa, moneda, fecha, periodo y una o varias líneas por referencia. **Registrar y conciliar** aplica automáticamente los importes compatibles. No se interpreta un archivo PDF/XML: esta versión utiliza captura manual estructurada.
4. Si una factura llegó antes que su provisión, queda pendiente. Después de aprobar la provisión, selecciona el mes de aplicación y pulsa **Conciliar** en la factura.
5. **Reporte mensual** muestra saldos, movimientos y facturas pendientes. **Descargar CSV para Excel** exporta todas las filas del alcance, independientemente de la paginación.

| Provisión | Neto facturado | Resultado |
| --- | --- | --- |
| 500 | 500 | Liquidada; saldo 0 |
| 500 | 300 | Parcial; saldo 200 arrastrado |
| 500 | Sin factura | Viva; saldo 500 arrastrado |
| 500 | 600 | Liquidada; 100 de factura pendientes/sin provisión |

**Reglas:** la aplicación concilia importes netos, sin impuestos, contra provisiones aprobadas de la misma referencia, empresa, proveedor, concepto y moneda. Si hay varias líneas compatibles, consume primero las de origen más antiguo. Las referencias y sus alias deben existir en el master. Los impuestos se guardan por separado; no se hace conversión automática entre USD y MXN. Una factura pendiente puede requerir una provisión adicional o corregir la captura mediante cancelación y nuevo registro.

El saldo de cada mes se calcula como **saldo inicial + altas + ajustes − liberaciones netas**. Las provisiones mantienen su mes de origen; el arrastre no crea copias ni nuevas provisiones. Los totales de cada moneda permanecen separados. Una provisión liquidada se conserva como `CLOSED`; no se borra ni se marca como cancelación administrativa.

**Cancelar factura** exige mes abierto y motivo, registra reversiones y restituye los saldos afectados. Los movimientos originales se conservan y el reporte de meses anteriores no cambia por una reversión posterior. La conciliación y reversión no pueden retroceder respecto del último mes con movimientos de la referencia. Los importes positivos/negativos del reporte distinguen aplicación y reversión.

Los reportes son consultas calculadas, **no cierres contables bloqueados**. Una captura o aprobación retroactiva en un periodo que sigue abierto puede modificar su reporte. Desde Provisiones, el reporte respeta referencia, responsable y operación consultados, incluyendo todos los estados. Desde Facturas, cubre todas las referencias autorizadas del mes elegido; la búsqueda de folio solo afecta la lista de facturas. El CSV separa filas `SALDO`, `MATCH`, `REVERSAL` y `UNPROVISIONED` para evitar sumar saldos y movimientos como si fueran el mismo dato.

### Permisos e historial

- **Finanzas y Super Admin:** consulta financiera de todos los responsables, apertura de periodos, creación y aprobación de provisiones, registro/conciliación/cancelación de facturas.
- **Gerencia:** consulta financiera e historial; sin cambios financieros.
- **Operaciones:** consulta de saldos, reporte e historial de sus propias referencias. Los permisos de edición de Masters se conservan.

El servidor obtiene la identidad del usuario autenticado. Los eventos nuevos guardan su nombre/correo, acción y valores anteriores/nuevos. Incluye altas, cambios de campos, vaciado de valores, documentos agregados, aprobaciones, aplicaciones y cancelaciones. No registra cada pulsación: registra cambios guardados. No se ofrece borrado físico de embarques; su cancelación es un cambio de estado auditado. La auditoría y las asignaciones financieras rechazan UPDATE/DELETE en PostgreSQL. La hora se muestra en Ciudad de México y los filtros de fechas del historial se indican en UTC.

### Actualizar una instalación existente

Esta versión requiere la migración **0004_financial_workflows** para vincular líneas de factura a embarques y habilitar los permisos de base de datos. No regeneres `.env`.

Con Docker, desde la raíz:

```powershell
git pull --ff-only origin main
docker compose build api migrate web
docker compose run --rm migrate
docker compose up -d api web
```

Sin Docker, detén el backend y el frontend, actualiza el repositorio y ejecuta `python -m alembic upgrade head` desde `backend`, utilizando la configuración existente de `MIGRATION_DATABASE_URL` y el intérprete del backend. Después reinicia ambos servicios; desde `frontend`, usa `npm.cmd start`. Recarga el navegador con Ctrl+F5.

### Verificación de este bloque

- Build Angular de producción correcto y **31 pruebas de navegador** aprobadas, incluyendo 7 nuevas de finanzas/historial y las 24 anteriores.
- Casos de API/migración probados con datos ficticios sobre PGlite (motor PostgreSQL embebido): liquidación exacta, arrastre, parciales, excedentes, duplicados, reversiones, moneda/concepto/proveedor, varias referencias, permisos de API, auditoría, periodos cerrados y FIFO.
- La batería de integración está preparada para PostgreSQL nativo y el rol restringido de producción en GitHub Actions. **PGlite no sustituye esa validación de permisos de base de datos ni la prueba de concurrencia nativa**. Docker y SSO real requieren validación en el entorno autorizado antes del piloto.

![Provisiones y conciliación con datos ficticios](frontend/docs/finance-preview.png)

![Historial con datos ficticios](frontend/docs/history-preview.png)
