# MasterLogistica

Aplicación de control de embarques. Incluye backend FastAPI/PostgreSQL y el primer bloque de Masters en Angular 21: acceso Microsoft, consulta, filtros, alta, edición y documentos por operación.

## Estado

- Referencias: nomenclatura versionada y catálogo de BU configurable.
- Inicio con accesos a Masters, Provisiones, Facturas e Historial. Masters por tipo de operación, sin selector de responsable, con vista ampliada y 50 filas por página. Se conserva la propiedad y autorización de cada registro.
- Detalle: edición con control de concurrencia, pedimentos, BL, contenedores, guías y seguimiento de incidencias.
- Demostración: disponible sin credenciales, con datos ficticios y sólo lectura. No consulta ni modifica registros operativos.
- Finanzas: provisiones por referencia, aprobación, conciliación de facturas con varias referencias, arrastre mensual, cancelación con reversión y reporte CSV.
- Historial: usuario, fecha, acción, referencia y valores anteriores/nuevos; filtros y registros inmutables.
- Importación del consolidado XLSX con vista previa, equivalencias de compañías/proveedores, prevención de duplicados y USD AMOUNT completo. Pendientes: lectura directa de PDF/XML, cierre contable bloqueado y validación en PostgreSQL nativo, Docker y Microsoft Entra ID real.

## Inicio local con un comando

El inicio predeterminado es **directo, sin Docker ni WSL**. Requiere Python 3.11 o posterior y Node compatible con Angular 21 (`^20.19.0`, `^22.12.0` o `^24.0.0`), instalados por el canal autorizado. Node 24.13.1 es compatible.

En Windows, desde la carpeta principal, ejecuta en CMD o abre con doble clic:

```bat
INICIAR_LOCAL.cmd
```

El lanzador inicia los servicios locales y abre **http://127.0.0.1:4200/** cuando responden. Conserva la ventana abierta. Si ya funciona tu instalación de Angular, reutiliza `node_modules`; no cambia `package.json` ni el lock para resolver Rollup. Instala dependencias con el lock solamente cuando faltan, cuando detecta un cambio posterior del lock o si solicitas `--install`.

Antes de iniciarlo, detén con **Ctrl+C en sus propias terminales** cualquier `npm.cmd start` o sesión de DataStage que ocupe los puertos 4200 u 8000. El control local también necesita el puerto 8317 en loopback. El lanzador informa si están ocupados y no termina procesos de otras aplicaciones.

### Sin base de datos: demostración

Si no existe `.env.native`, se abre el modo de **demostración de solo lectura**. Selecciona **Ver demostración** en la pantalla de acceso. Utiliza datos ficticios; no permite guardar embarques, provisiones ni facturas. No necesita PostgreSQL, credenciales Microsoft ni dependencias Python del backend. Un servidor mínimo atiende la configuración de acceso y evita el error de proxy `ECONNREFUSED`.

Para forzar este modo aunque exista una configuración de base de datos:

```bat
INICIAR_LOCAL.cmd --demo
```

### Con base de datos: desarrollo completo

Para guardar datos necesitas una **base PostgreSQL de desarrollo autorizada** y configurar Microsoft Entra y los usuarios de la aplicación. La aplicación no sustituye PostgreSQL por SQLite ni habilita acceso operativo sin autenticación.

Crea la configuración una sola vez:

```bat
copy .env.native.example .env.native
```

Edita `.env.native` con el endpoint, base y credenciales de desarrollo proporcionados por el DBA. `DATABASE_URL` corresponde al usuario de la API. Usa una base dedicada a desarrollo, nunca una base operativa para pruebas locales. Conserva `APP_ENV=development`.

El DBA puede aplicar previamente las migraciones y dejar `MIGRATION_DATABASE_URL` vacía. Si proporciona una identidad separada de migración, el lanzador ejecuta `alembic upgrade head` antes de la API y retira esas credenciales del entorno del proceso de la API. Configura también los valores `ENTRA_*`, las compañías y el catálogo de BU. El aprovisionamiento de usuarios sigue el procedimiento de **Configuración de acceso y catálogos**.

Después ejecuta `INICIAR_LOCAL.cmd`. En el primer arranque crea `.venv` e instala los requisitos bloqueados del backend. Si ya dispones de un intérprete con las dependencias aprobadas, puedes indicar su ruta:

```bat
INICIAR_LOCAL.cmd --python "C:\ruta\aprobada\python.exe" --skip-install
```

`--skip-install` impide instalar dependencias y comprueba que estén disponibles. Las instalaciones requieren acceso autorizado a npm y al repositorio Python, o a sus espejos corporativos. Los bloqueos de Application Control sobre binarios de Node también pueden afectar este modo; se resuelven mediante TI, sin cambiar las políticas del equipo.

### Detener y revisar

```bat
DETENER_LOCAL.cmd
VER_ESTADO.cmd
VER_LOGS.cmd
```

También puedes detenerlo con Ctrl+C en la ventana de inicio. El cierre usa los procesos de la sesión creada desde esta carpeta; no busca ni termina procesos por nombre. No borra la base, `.env.native` ni `.env`. Los logs se guardan en `.local-dev/`, excluido de Git, y el visor oculta las credenciales de la configuración.

Opciones: `--no-browser` evita abrir el navegador; `--timeout 300` amplía la espera de salud, entre 10 y 600 segundos. `--install` vuelve a instalar dependencias con los locks. Angular conserva la recarga automática al editar el frontend. En Linux se utilizan las mismas acciones:

```sh
python3 scripts/local_dev.py start --no-browser
python3 scripts/local_dev.py status
python3 scripts/local_dev.py stop
```

### Docker opcional

Solo si Docker está autorizado y su motor Linux y Compose v2 funcionan:

```bat
INICIAR_LOCAL.cmd --mode docker
DETENER_LOCAL.cmd --mode docker
VER_ESTADO.cmd --mode docker
VER_LOGS.cmd --mode docker
```

Este modo utiliza los cuatro servicios de `compose.yaml`: PostgreSQL, migración, API y web. Crea `.env` solo si falta y conserva las contraseñas existentes. Comprueba los puertos 5432, 8000 y 4200, prepara imágenes, aplica migraciones y espera a la API y la interfaz. La primera construcción puede tardar varios minutos. Los siguientes inicios reutilizan imágenes si no cambian código y configuración. `--rebuild` fuerza la reconstrucción. La interfaz de este modo está compilada; vuelve a iniciar para incorporar cambios.

El lanzador opera únicamente el contexto Docker local y los contenedores de esta carpeta. Al detener usa `compose stop`: conserva el volumen PostgreSQL y sus registros. No cambia Hyper-V, firewall, permisos de `docker.sock` ni políticas de seguridad.

Los problemas corporativos anteriores sí pueden reaparecer si se elige Docker:

| Antecedente | Aplicación a MasterLogistica |
| --- | --- |
| Docker Desktop dentro de una VM Windows sin virtualización anidada | Puede impedir el arranque del motor. El inicio directo no utiliza ese motor. Docker Engine directamente en Linux no necesita WSL2 ni una VM adicional para sus contenedores Linux. |
| Firewall o proxy bloqueando Docker Hub | Puede bloquear las imágenes también en Linux. TI debe validar registro, autenticación, descargas, proxy y certificados; los tres dominios de un ticket previo no garantizan cobertura actual. El inicio directo puede requerir npm y Python al instalar dependencias. |
| Permisos de `docker.sock` | Afectan al modo Docker. No usar `chmod 666`: el acceso al daemon permite operaciones de alto privilegio. TI debe definir quién despliega y con qué permisos. |
| Aprobaciones y licencia | Revisar con TI el uso corporativo de Docker Desktop y su licencia. Un despliegue con Engine en Linux cambia los componentes necesarios, pero mantiene las autorizaciones corporativas de red, servicios y acceso. |

Para producción en Linux con el clúster corporativo, se debe preparar una configuración de despliegue separada: API como servicio, frontend compilado servido por el proxy web, HTTPS, Entra y conexión al endpoint PostgreSQL autorizado. Docker es una opción de empaquetado. El `compose.yaml` actual incluye una base local y no debe usarse sin adaptar para apuntar al clúster. El lanzador nativo está limitado a desarrollo y no instala servicios de producción.

Referencias oficiales: [Docker Desktop en VM/VDI](https://docs.docker.com/desktop/setup/vm-vdi/), [permisos en Linux](https://docs.docker.com/engine/install/linux-postinstall/), [licencia de Desktop](https://docs.docker.com/subscription-billing/desktop-license/) y [lista de acceso de red](https://docs.docker.com/desktop/enterprise/allow-list/).

Las comprobaciones del lanzador cubren migraciones, reutilización, puertos ocupados, propiedad de servicios, cierre de sesión, demostración y ocultación de credenciales. La ejecución con Windows corporativo, PostgreSQL real y Entra debe validarse en ese entorno. CI incluye pruebas del lanzador en Windows y Linux y arranque Docker real en Linux, sujeto a disponibilidad de runners.

## Arranque manual con Docker

Requisitos: Docker Engine en Linux o Docker Desktop autorizado en Windows, con contenedores Linux y Compose v2. Para generar la configuración inicial, Python 3.11+.

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

Abre **http://127.0.0.1:4200**. Las llamadas `/api` se dirigen a `127.0.0.1:8000`. Puedes entrar en la demostración aunque el backend no esté iniciado, pero el proxy mostrará errores al consultar la configuración. Usa el lanzador predeterminado para iniciar también el servicio de configuración de la demo. Si ya tienes el servicio `web` de Docker usando el puerto 4200, detenlo con `docker compose stop web` desde la raíz antes de iniciar Angular.

## Configuración de acceso y catálogos

La aplicación necesita dos registros de Entra: API y SPA. En `.env` para Docker o `.env.native` para el inicio directo, configura `ENTRA_TENANT_ID`, `ENTRA_API_CLIENT_ID`, `ENTRA_FRONTEND_CLIENT_ID` y `ENTRA_ALLOWED_CLIENT_IDS` (arreglo JSON que incluya el ID de la SPA). La API espera tokens v2 y el permiso delegado `access_as_user`.

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
| Gerencia (`MANAGER`) | Todos los responsables autorizados por operación | Sólo lectura |
| Finanzas (`FINANCE`) | Registros propios según el alcance actual | Sin alta ni edición operativa; los permisos de provisiones se gestionan por separado |
| Super Admin (`SUPER_ADMIN`) | Todos los responsables autorizados por operación | Edición y administración de usuarios; las altas se asignan siempre al usuario autenticado |

La interfaz no carga embarques hasta seleccionar una operación. Las rutas `/masters/shipments` y `/masters/summary` exigen un único `operation_code`; `owner_id` es opcional y conserva sus comprobaciones de autorización. Gerencia y Super Admin pueden consultar la operación completa. Los otros roles siguen limitados a sus registros. El servidor asigna el dueño autenticado en cada alta.

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

La interfaz usa una hoja de cálculo como área principal: fondo blanco, tipografía del sistema, encabezados fijos, referencia fija en escritorio y columnas separadas para cada dato. No carga registros hasta abrir un master por tipo de operación. La demostración sigue siendo de solo lectura.

## Edición del master

- Doble clic, Enter, F2 o **Editar celda** abre la celda seleccionada. Tab y Enter confirman la edición y avanzan; Escape cancela la edición actual. Las flechas cambian de celda.
- Shift con flechas o clic selecciona un rango. Ctrl+C copia el rango; Ctrl+V pega desde Excel. Las fechas aceptan `dd/mm/aaaa` o `aaaa-mm-dd`. Los estados y proveedores se validan contra sus catálogos. Un rango inválido se rechaza completo.
- **Guardar cambios** o Ctrl+S envía los cambios pendientes. **Deshacer** o Ctrl+Z revierte ediciones aún no guardadas; **Descartar** elimina los cambios pendientes tras confirmar. Salir, cambiar de master, filtrar o cambiar de página solicita confirmar si hay ediciones pendientes.
- Cada fila se guarda con control de versión. Si una fila falla, se conservan sus cambios y los de las filas aún no enviadas. Los conflictos y los guardados sin confirmación requieren **Recargar fila** antes de volver a editar esa fila. El conjunto de filas no es una transacción única.
- Referencia y BU están protegidas porque forman parte de la identidad de la operación. La propiedad del registro permanece protegida y el tipo de operación lo define el master. La edición respeta los roles del servidor.
- **Nuevo embarque** genera la referencia mediante el servidor. Abrir una referencia permite consultar o editar su detalle, incidencias y documentos.
- **Exportar página CSV** descarga las filas de la página visible, incluidos los cambios pendientes; no exporta el master completo ni un archivo XLSX. Se neutralizan valores que Excel podría interpretar como fórmulas. No se implementa cálculo de fórmulas ni importación de libros como masters; la carga del consolidado de facturación se realiza en su sección dedicada.

Los registros modificados permanecen visibles hasta actualizar o volver a aplicar los filtros.

![Masters con datos ficticios](frontend/docs/masters-preview.png)

## Provisiones, facturas e historial

El menú principal incorpora **Provisiones**, **Facturas y conciliación** e **Historial**. La demostración incluye ejemplos financieros ficticios de octubre de 2026 y continúa siendo de solo lectura.

### Flujo financiero

1. Finanzas o Administración selecciona un mes y pulsa **Abrir periodo**. Esto crea un periodo abierto; no cierra ni reemplaza otros meses.
2. En **Provisiones**, captura referencia existente, proveedor, concepto, línea de costo, mes de origen, moneda, importe neto y cargos extra. Guarda el borrador y pulsa **Aprobar**. Los borradores no afectan los saldos.
3. En **Facturas y conciliación**, registra folio, proveedor, empresa, moneda, fecha, periodo y una o varias líneas por referencia. **Registrar y conciliar** aplica automáticamente los importes compatibles. También puedes usar **Subir consolidado Excel**, descrito abajo. La captura manual sigue disponible; no se interpretan archivos PDF/XML.
4. Si una factura llegó antes que su provisión, queda pendiente. Después de aprobar la provisión, selecciona el mes de aplicación y pulsa **Conciliar** en la factura.
5. **Reporte mensual** muestra saldos, movimientos y facturas pendientes. **Descargar CSV para Excel** exporta todas las filas del alcance, independientemente de la paginación.

| Provisión | Neto facturado | Resultado |
| --- | --- | --- |
| 500 | 500 | Liquidada; saldo 0 |
| 500 | 300 | Parcial; saldo 200 arrastrado |
| 500 | Sin factura | Viva; saldo 500 arrastrado |
| 500 | 600 | Liquidada; 100 de factura pendientes/sin provisión |

**Reglas:** la captura manual concilia el neto; la importación XLSX concilia **USD AMOUNT completo**, ya convertido en el archivo. Ambos flujos aplican el importe conciliable contra provisiones aprobadas de la misma referencia, empresa, proveedor, concepto y moneda. Si hay varias líneas compatibles, consume primero las de origen más antiguo. Las referencias y sus alias deben existir en el master. En captura manual los impuestos se guardan por separado. En la importación, moneda e impuestos originales se conservan como evidencia y no se vuelven a sumar ni convertir; el importe conciliable se registra en USD. Las provisiones MXN existentes no se convierten ni se cancelan con una importación USD. Una factura pendiente puede requerir una provisión adicional o corregir la captura mediante cancelación y nuevo registro.

El saldo de cada mes se calcula como **saldo inicial + altas + ajustes − liberaciones netas**. Las provisiones mantienen su mes de origen; el arrastre no crea copias ni nuevas provisiones. Los totales de cada moneda permanecen separados. Una provisión liquidada se conserva como `CLOSED`; no se borra ni se marca como cancelación administrativa.

**Cancelar factura** exige mes abierto y motivo, registra reversiones y restituye los saldos afectados. Los movimientos originales se conservan y el reporte de meses anteriores no cambia por una reversión posterior. La conciliación y reversión no pueden retroceder respecto del último mes con movimientos de la referencia. Los importes positivos/negativos del reporte distinguen aplicación y reversión.

Los reportes son consultas calculadas, **no cierres contables bloqueados**. Una captura o aprobación retroactiva en un periodo que sigue abierto puede modificar su reporte. Desde Provisiones, el reporte respeta referencia, responsable y operación consultados, incluyendo todos los estados. Desde Facturas, cubre todas las referencias autorizadas del mes elegido; la búsqueda de folio solo afecta la lista de facturas. El CSV separa filas `SALDO`, `MATCH`, `REVERSAL` y `UNPROVISIONED` para evitar sumar saldos y movimientos como si fueran el mismo dato.

### Permisos e historial

- **Finanzas y Super Admin:** consulta financiera de todos los responsables, apertura de periodos, creación y aprobación de provisiones, registro/conciliación/cancelación de facturas.
- **Gerencia:** consulta financiera e historial; sin cambios financieros.
- **Operaciones:** consulta de saldos, reporte e historial de sus propias referencias. Los permisos de edición de Masters se conservan.

El servidor obtiene la identidad del usuario autenticado. Los eventos nuevos guardan su nombre/correo, acción y valores anteriores/nuevos. Incluye altas, cambios de campos, vaciado de valores, documentos agregados, aprobaciones, aplicaciones y cancelaciones. No registra cada pulsación: registra cambios guardados. No se ofrece borrado físico de embarques; su cancelación es un cambio de estado auditado. La auditoría y las asignaciones financieras rechazan UPDATE/DELETE en PostgreSQL. La hora se muestra en Ciudad de México y los filtros de fechas del historial se indican en UTC.

### Actualizar una instalación existente

Esta versión requiere **0005_invoice_excel**, además de las migraciones anteriores, para conservar la evidencia original de la importación. No regeneres `.env`.

Con Docker, desde la raíz:

```powershell
git pull --ff-only origin main
docker compose build api migrate web
docker compose run --rm migrate
docker compose up -d api web
```

Sin Docker, detén el backend y el frontend, actualiza el repositorio y ejecuta `python -m alembic upgrade head` desde `backend`, utilizando la configuración existente de `MIGRATION_DATABASE_URL` y el intérprete del backend. Después reinicia ambos servicios; desde `frontend`, usa `npm.cmd start`. Recarga el navegador con Ctrl+F5.

### Verificación de este bloque

- Build Angular de producción correcto y **34 pruebas de navegador** verificadas, incluyendo importación con vista previa, equivalencias, detalle por referencia, inicio y vista ampliada.
- Casos de API/migración probados con datos ficticios sobre PGlite (motor PostgreSQL embebido): liquidación exacta, arrastre, parciales, excedentes, duplicados, reversiones, moneda/concepto/proveedor, varias referencias, permisos de API, auditoría, periodos cerrados y FIFO.
- La batería de integración está preparada para PostgreSQL nativo y el rol restringido de producción en GitHub Actions. **PGlite no sustituye esa validación de permisos de base de datos ni la prueba de concurrencia nativa**. Docker y SSO real requieren validación en el entorno autorizado antes del piloto.

![Provisiones y conciliación con datos ficticios](frontend/docs/finance-preview.png)

![Historial con datos ficticios](frontend/docs/history-preview.png)

### Importar el consolidado de facturación

1. En **Facturas y conciliación**, abre **Subir consolidado Excel** y elige un mes.
2. Selecciona un `.xlsx` de hasta 10 MB con la hoja `CONSOLIDADO <año>`. Se lee esa hoja; las hojas auxiliares no se importan.
3. El mes se obtiene de `MOUTH` y el año del nombre de la hoja. Las facturas de otros meses se muestran aparte. La fecha de factura se conserva independientemente del periodo del gasto.
4. Si una compañía o proveedor no coincide con el catálogo, selecciona su equivalencia y actualiza la vista previa. No se crean proveedores ni embarques automáticamente.
5. Revisa las pestañas **Listas**, **Revisar**, **Ya registradas** y **Otros meses**. Solo las listas se pueden importar. Abre primero el periodo contable si no existe.
6. **Importar facturas listas** registra y concilia por lotes de hasta 100 facturas. Cada lote es atómico. Si falla un lote, los anteriores confirmados permanecen guardados; la vista previa reconoce sus facturas al reintentar.

La identidad de factura usa compañía, proveedor y folio normalizado. El concepto se toma del primer `TYPE` (Freight, Broker, Storage u Other); se respeta cada concepto sin sumarlos entre sí. La referencia debe coincidir de manera única con un embarque o alias registrado. Un movimiento `PAQUETERIA` sin referencia concreta necesita corregirse o vincularse antes de importar.

**El importe conciliable es la columna `USD AMOUNT` completa**, redondeada a cuatro decimales según la precisión del sistema. No se recalculan fórmulas ni tipos de cambio. Un resultado de fórmula sin valor guardado requiere abrir, recalcular y guardar el Excel. `TOTAL`, subtotal, impuestos, moneda original, fórmula USD, fila, nombre y huella del archivo quedan guardados como evidencia. La columna interna `net_amount` contiene la base conciliable; `source_data.amount_basis = USD_AMOUNT` distingue las importaciones de la captura manual neta. El reporte CSV incluye esta base.

Una factura con varias referencias e importe concentrado en una fila, otra en cero, no se reparte automáticamente: se bloquea el grupo completo hasta corregir el reparto en el Excel. También requieren revisión las notas de crédito, negativos, fechas inválidas, conceptos desconocidos o fechas/meses inconsistentes dentro de la factura. Si dos nombres de proveedor o compañía terminan identificando la misma factura al aplicar equivalencias, se bloquea su importación hasta unificar los datos, incluso si uno de los grupos tiene errores o pertenece a otro mes. No se dividen ni sustituyen referencias por coincidencia aproximada.

Desde el master, selecciona una celda y pulsa **Movimientos de referencia**. Desde Provisiones o el detalle de una factura, pulsa la referencia. La consulta reúne provisiones, facturas y auditoría, respeta el alcance del usuario y permite cargar el historial completo por páginas. **Ampliar master** oculta controles secundarios temporalmente sin perder las filas ni los cambios pendientes.

Validación de la actualización XLSX: 177 pruebas de backend sin base externa y 30 casos de parser/finanzas sobre PGlite aprobados. La lectura se comprobó también contra el consolidado suministrado, sin incorporar datos operativos al repositorio. Las pruebas de navegador usan respuestas de API y datos ficticios; la integración con PostgreSQL nativo y Microsoft Entra ID sigue pendiente en el entorno autorizado.

![Vista previa de importación con datos ficticios](frontend/docs/invoice-import-preview.png)
