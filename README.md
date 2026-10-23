# MasterLogistica

Aplicación de control de embarques. Incluye backend FastAPI con SQLite local y PostgreSQL corporativo y el primer bloque de Masters en Angular 21: acceso Microsoft, consulta, filtros, alta, edición y documentos por operación.

Preparación de producción: [guía de despliegue corporativo](docs/DESPLIEGUE_EMPRESA.md), con alternativas Linux, solicitud ITPM, licencias, red de entrada/salida y diagnóstico desde las estaciones de usuarios.

La propuesta basada en las tecnologías permitidas indicadas por el usuario es **Angular + Python FastAPI + PostgreSQL + Microsoft Entra ID en Linux interno, sin Docker**, con código y entregas corporativas mediante JE Git. La recomendación de contenedores/AKS de la referencia recibida se refiere a aplicaciones para varias regiones; confirmar ese alcance si aplica al proyecto.

## Estado

- Referencias: nomenclatura versionada y catálogo de BU M01, M19, M23, M45 y M46.
- Inicio con accesos a Masters, Provisiones, Facturas e Historial. Masters por responsable (DENI, MAG, NAT, ANDREA y ALEXA), con todos sus tipos de operación, con vista ampliada y 50 filas por página. Se conserva la propiedad y autorización de cada registro.
- Detalle: edición con control de concurrencia, pedimentos, BL, contenedores, guías y seguimiento de incidencias.
- Desarrollo local: API real, base SQLite persistente y usuario local con permisos de edición; sin Docker, servidor de base de datos ni cuenta Microsoft.
- Demostración: disponible sin credenciales, con datos ficticios y sólo lectura. No consulta ni modifica registros operativos.
- Práctica de masters: edición de ejemplos ficticios, pegado desde Excel y guardado en el navegador, sin conexión a la API. Se abre con **Practicar con el master** y se puede restablecer.
- Hoja ampliada: ocupa el espacio disponible en escritorio, con texto y filas más grandes, tamaño 100/115/130 %, filtros plegables y navegación que desplaza solo la cuadrícula.
- Finanzas: provisiones por referencia, aprobación, conciliación de facturas con varias referencias, arrastre mensual, cancelación con reversión y reporte CSV.
- Historial: usuario, fecha, acción, referencia y valores anteriores/nuevos; filtros y registros inmutables.
- Importación del consolidado XLSX con vista previa, equivalencias de compañías/proveedores, prevención de duplicados y USD AMOUNT completo. Pendientes: lectura directa de PDF/XML, cierre contable bloqueado y validación en PostgreSQL nativo, Docker y Microsoft Entra ID real.

## Inicio local con un comando

El inicio predeterminado es **directo, sin Docker ni WSL**. Requiere Python 3.11 o posterior y Node compatible con Angular 21 (`^20.19.0`, `^22.12.0` o `^24.0.0`), instalados por el canal autorizado. Node 24.13.1 es compatible.

El lock fija Rollup **4.63.4**, la versión que el usuario comprobó que carga en su equipo, e incluye las dependencias opcionales Windows y Linux. Una política diferente de Application Control debe validarse con TI; el proyecto no cambia esas políticas.

En Windows, desde la carpeta principal, ejecuta en CMD o abre con doble clic:

```bat
INICIAR_LOCAL.cmd
```

El lanzador inicia los servicios locales y abre **http://127.0.0.1:4200/** cuando responden. Conserva la ventana abierta. Si ya funciona tu instalación de Angular, reutiliza `node_modules`; no cambia `package.json` ni el lock para resolver Rollup. Instala dependencias con el lock solamente cuando faltan, cuando detecta un cambio posterior del lock o si solicitas `--install`.

Los locks de Python son universales: excluyen `uvloop` de Windows e incluyen `tzdata` con versión y hashes. El lanzador usa el Python instalado y, en Windows, solicita SQLAlchemy sin sus extensiones compiladas mediante su opción oficial de instalación. Conserva las dependencias que ya satisfacen las versiones fijadas; no fuerza su reinstalación. No hace falta instalar Python 3.11 ni regenerar los locks en la computadora del usuario.

Antes de iniciarlo, detén con **Ctrl+C en sus propias terminales** cualquier `npm.cmd start` o sesión de DataStage que ocupe los puertos 4200 u 8000. El control local también necesita el puerto 8317 en loopback. El lanzador informa si están ocupados y no termina procesos de otras aplicaciones.

### Desarrollo local editable (predeterminado)

Sin configuración adicional, el lanzador prepara `.venv`, inicia **la API real y Angular** y crea automáticamente **`.data/masterlogistica.db`** en la raíz del proyecto. Entras en el master local de **DENI**, con acceso de administración para seleccionar los cinco responsables, con permisos para crear y editar embarques, documentos, provisiones y facturas. Los cambios se guardan en ese archivo y continúan después de cerrar el navegador, detener la aplicación o reiniciar el equipo. La misma API aplica validaciones, control de versiones y auditoría.

Se preparan las identidades locales DENI, MAG, NAT, ANDREA y ALEXA, las BU `M01`/`M19`/`M23`/`M45`/`M46` y un proveedor de ejemplo; las tablas operativas empiezan vacías. No se necesita PostgreSQL, SQL Server ni Microsoft Entra para desarrollar en esta computadora. El catálogo de proveedores dispone de altas y cambios mediante la API local (`/docs`). Los datos locales no se publican ni se transfieren automáticamente al servidor.

`.env.native` es opcional. Si quieres cambiar catálogos o la ubicación del archivo, copia `.env.native.example` a `.env.native` y edita sus valores. Si ya tenías una `.env.native` con PostgreSQL/Entra, se conserva y sigue utilizando esa conexión: para elegir SQLite, renómbrala como respaldo y usa la nueva plantilla. No se migra ni borra la base anterior.

Para respaldar tus datos, detén la aplicación y copia `.data/masterlogistica.db` a una ubicación segura. Es una base personal: no abras el mismo archivo simultáneamente desde varias computadoras ni lo uses como base compartida por regiones. SQLite, configuración y logs están excluidos de Git y del paquete productivo.

El modo local solo admite solicitudes desde loopback y rechaza proxies y orígenes externos. `APP_ENV=production` exige PostgreSQL y Microsoft Entra: la identidad local no se puede activar en producción.

### Arranque manual, similar a DataStage

Primera instalación, desde la raíz en CMD (Python 3.13 es un ejemplo compatible):

```bat
py -3.13 -m venv .venv
set "DISABLE_SQLALCHEMY_CEXT=1"
.venv\Scripts\python.exe -m pip install --require-hashes --no-binary=sqlalchemy --no-cache-dir -r backend\requirements.lock
set "DISABLE_SQLALCHEMY_CEXT="
cd frontend
npm.cmd ci
```

Después, en una terminal situada en `MasterLogistica\backend`:

```bat
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

En otra terminal situada en `MasterLogistica\frontend`:

```bat
npm.cmd start
```

Abre **http://127.0.0.1:4200/**. Conserva ambas terminales abiertas. **MasterLogistica no necesita `app.worker`**: actualmente sus operaciones se ejecutan en la API. Si usas el lanzador, este abre ambos procesos por ti. El arranque manual toma las variables del entorno y un posible `backend/.env`; sin ellas usa SQLite local. El lanzador toma exclusivamente `.env.native` para la configuración de la aplicación y descarta conexiones corporativas heredadas del entorno.

Para un Python autorizado que ya contenga las dependencias:

```bat
INICIAR_LOCAL.cmd --python "C:\ruta\aprobada\python.exe" --skip-install
```

Las instalaciones iniciales requieren acceso a npm y al repositorio Python o a sus espejos corporativos. `--skip-install` comprueba los paquetes y evita instalarlos. Los bloqueos de Application Control deben resolverse mediante TI.

### PostgreSQL de desarrollo (opcional)

Si necesitas comprobar el motor corporativo antes del despliegue, usa una base de desarrollo autorizada y define en `.env.native`:

```dotenv
APP_ENV=development
AUTH_MODE=entra
DATABASE_URL=postgresql+psycopg://masterlogistica_app:PASSWORD@HOST:5432/DEVELOPMENT_DATABASE
ENTRA_TENANT_ID=ID-DEL-TENANT
ENTRA_API_CLIENT_ID=ID-DE-LA-API
ENTRA_FRONTEND_CLIENT_ID=ID-DE-LA-SPA
ENTRA_ALLOWED_CLIENT_IDS=["ID-DE-LA-SPA"]
COMPANY_CODES=["JE_MX"]
BUSINESS_UNITS={"M01":"M01","M19":"M19","M23":"M23","M45":"M45","M46":"M46"}
```

Completa los identificadores y credenciales reales por el canal autorizado. El DBA prepara el esquema o proporciona `MIGRATION_DATABASE_URL` con un rol separado. El lanzador aplica Alembic si recibe esa identidad y la retira antes de iniciar la API. Aprovisiona los usuarios como indica **Configuración de acceso y catálogos**. Nunca uses una base operativa para pruebas locales.

SQLite permite desarrollar sin instalar un servidor de base de datos. El despliegue corporativo conserva PostgreSQL; SQL Server requeriría adaptar y validar sus migraciones y consultas, y no es necesario para simplificar este inicio.

### Demostración opcional

```bat
INICIAR_LOCAL.cmd --demo
```

Abre la pantalla de acceso con **Ver demostración** y **Practicar con el master**. La demostración es de solo lectura y la práctica guarda ejemplos únicamente en el navegador. Ambas siguen separadas de la API y de la base SQLite. Para trabajar con datos locales persistentes, inicia sin `--demo`.

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
| Solicitud ITPM para descargas | Preparar una solicitud específica de MasterLogistica: propósito, componentes, software y destinos. Engine de código abierto, pulls anónimos y Linux no sustituyen la autorización de red. |
| Funciona en el servidor pero no desde otra estación | Comprobar listener, proxy, DNS, TLS, rutas y firewalls. El Compose actual publica en `127.0.0.1` para uso local; producción necesita una entrada HTTPS corporativa. Un timeout no demuestra por sí solo que `ufw` sea la causa. |

Para producción en Linux con el clúster corporativo, se debe preparar una configuración de despliegue separada: API como servicio, frontend compilado servido por el proxy web, HTTPS, Entra y conexión al endpoint PostgreSQL autorizado. Docker es una opción de empaquetado. El `compose.yaml` actual incluye una base local y no debe usarse sin adaptar para apuntar al clúster. El lanzador nativo está limitado a desarrollo y no instala servicios de producción.

Referencias oficiales: [Docker Desktop en VM/VDI](https://docs.docker.com/desktop/setup/vm-vdi/), [permisos en Linux](https://docs.docker.com/engine/install/linux-postinstall/), [licencia de Desktop](https://docs.docker.com/subscription-billing/desktop-license/) y [lista de acceso de red](https://docs.docker.com/desktop/enterprise/allow-list/).

Las comprobaciones del lanzador cubren migraciones, reutilización, puertos ocupados, propiedad de servicios, cierre de sesión, demostración y ocultación de credenciales. La ejecución con Windows corporativo y Entra debe validarse en ese entorno. CI incluye pruebas del lanzador en Windows/Linux y del proxy HTTPS nativo. La comprobación Docker es opcional mediante ejecución manual del workflow.

## Despliegue Linux sin Docker

El perfil productivo está en [deploy/linux/README.md](deploy/linux/README.md). Incluye servicio systemd, Nginx HTTPS, configuración de salida por proxy, roles PostgreSQL separados, comprobaciones y activación de entregas versionadas.

Desde Windows, `PREPARAR_ENTREGA.cmd` construye Angular en producción y prepara el paquete del servidor. En Linux, `python3 scripts/build_release.py` hace lo mismo. El servidor recibe la interfaz compilada: no necesita Node, Angular CLI ni Docker. Se puede incluir un wheelhouse Linux para instalar Python sin acceso a Internet.

`deploy/linux/configure.py` genera la configuración a partir del nombre DNS asignado. TI completa endpoint/credenciales PostgreSQL, CA, certificado HTTPS y Entra. La instalación conserva los secretos existentes; la activación comprueba las conexiones, aplica Alembic con el rol migrador y espera la disponibilidad de la API. `scripts/check_deployment.py` permite comprobar HTTPS y configuración pública Entra desde una estación autorizada.

La API acepta encabezados de proxy solo de direcciones individuales configuradas y permanece en loopback. Las conexiones PostgreSQL productivas verifican certificado y nombre de servidor. El modo local usa `INICIAR_LOCAL.cmd` con SQLite editable como opción predeterminada; producción utiliza exclusivamente PostgreSQL y Entra.

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

El perfil corporativo (`AUTH_MODE=entra`) necesita dos registros de Entra: API y SPA. En `.env` para Docker o `.env.native` para el inicio directo, configura `ENTRA_TENANT_ID`, `ENTRA_API_CLIENT_ID`, `ENTRA_FRONTEND_CLIENT_ID` y `ENTRA_ALLOWED_CLIENT_IDS` (arreglo JSON que incluya el ID de la SPA). La API espera tokens v2 y el permiso delegado `access_as_user`.

Registra **http://127.0.0.1:4200/** como URI de redirección de tipo **Single-page application**. Si usas `localhost`, registra también **http://localhost:4200/**. La URL debe coincidir con la que abras. La SPA no usa secretos de cliente.

`Empresa` se captura manualmente como en el master (hasta 32 caracteres). `COMPANY_CODES` aporta sugerencias iniciales; las empresas registradas aparecen también en el catálogo para facturación e importación. Las BU permitidas son M01, M19, M23, M45 y M46. Se pueden personalizar sus descripciones desde un JSON, por ejemplo `{"M01":"Descripción interna"}`:

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
| Operaciones (`OPERATOR`) | Su propio master con todos sus tipos de operación | Alta y edición de registros propios |
| Gerencia (`MANAGER`) | Un master por cada responsable autorizado | Sólo lectura |
| Finanzas (`FINANCE`) | Registros propios según el alcance actual | Sin alta ni edición operativa; los permisos de provisiones se gestionan por separado |
| Super Admin (`SUPER_ADMIN`) | Un master por cada responsable autorizado | Edición y administración de usuarios; puede crear en el master seleccionado |

La interfaz no carga embarques hasta abrir el master de un responsable. Las rutas `/masters/shipments` y `/masters/summary` aceptan `owner_id` y un filtro opcional `operation_code`. La pantalla envía siempre el responsable seleccionado. Operaciones conserva el acceso a sus registros; Gerencia y Administración pueden consultar los responsables autorizados. Sólo Administración puede crear registros para otro responsable; la referencia y su consecutivo se generan con el código del dueño seleccionado, mientras la auditoría registra al usuario que realizó el alta.

Los códigos de analista 1–5 identifican a los integrantes de logística en el catálogo. Las cinco identidades de la demostración son ficticias; las cuentas reales deben aprovisionarse con sus códigos verificados. Los endpoints generales de embarques mantienen la consulta consolidada autorizada para Gerencia y Super Admin.

## Verificación

Configuración local editable: **239 pruebas de backend aprobadas**, incluidas **38 pruebas locales sobre SQLite**, y **29 pruebas de lanzadores/configuración**. Compilación Angular de producción y **42 casos existentes de navegador** aprobados; además, una prueba completa usa Uvicorn + Angular reales para crear, editar y recuperar los datos desde otra sesión de navegador, sin API simulada. El inicio/cierre del lanzador nativo también se comprobó con la base persistente.

La entrega Linux se construyó y se revisó que excluyera bases SQLite y secretos. **39 pruebas específicas de PostgreSQL nativo** quedan pendientes de la base aislada configurada en CI. Estas pruebas locales no certifican Entra, el clúster ni las políticas del Windows corporativo.

Para repetir la prueba completa de inicio local, con las dependencias de backend y frontend instaladas, ejecuta desde `frontend`: `npx playwright test --config playwright.local.config.ts`. Usa una base temporal y requiere los puertos 4200/8000 libres. `LOCAL_TEST_PYTHON` permite indicar el Python que tiene los paquetes del backend; por defecto usa `python`.

Frontend:

```powershell
cd frontend
npm.cmd run build
npx.cmd playwright install chromium
npm.cmd test
```

Los casos de hoja de cálculo incluyen edición, pegado, conflictos, navegación rápida y permisos. Los casos financieros se ejecutan también sobre SQLite local; la validación específica del motor PostgreSQL se mantiene separada.

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

La interfaz usa una hoja de cálculo como área principal: fondo blanco, tipografía del sistema, encabezados fijos, referencia fija en escritorio y columnas separadas para cada dato. No carga registros hasta abrir el master de un responsable. La demostración sigue siendo de solo lectura.

## Edición del master

- La vista normal reúne navegación, selección del responsable y acciones en una cabecera compacta. Los registros ocupan la mayor parte de la ventana; los filtros empiezan plegados y se abren con **Mostrar filtros**. **Tamaño** cambia texto, altura de filas y ancho de columnas a 100/115/130 % y conserva esa preferencia. **Ampliar master** aprovecha todavía más la ventana sin descartar cambios.
- Haz clic en una celda editable y empieza a escribir para reemplazar su contenido, incluidos fechas, estados y proveedores. Las fechas se pueden escribir como `dd/mm/aaaa` o `aaaa-mm-dd`; estados y proveedores deben coincidir con su catálogo. Doble clic, Enter, F2 o **Editar celda** abre el valor actual (con lista para estados y proveedores). Tab y Enter confirman la edición y avanzan; Escape cancela la edición actual. Las flechas cambian de celda.
- Mantener una flecha mueve la selección y desplaza únicamente el interior de la hoja. Encabezados y referencia fija no ocultan la celda activa. Inicio/Fin van al extremo de la fila; Ctrl+Inicio/Ctrl+Fin a los extremos de la página cargada; RePág/AvPág desplazan la selección una pantalla dentro de esa página.
- Todas las columnas del master permiten editar y pegar valores, incluidas **Referencia**, **BU**, **Tipo de operación** y **Empresa**. Enter abre el editor de la celda; Ctrl+Enter o el botón ↗ de la referencia abre el detalle del embarque, donde también se puede modificar su identificación.
- Shift con flechas o clic selecciona un rango. Ctrl+C copia el rango; Ctrl+V pega desde Excel. Las fechas aceptan `dd/mm/aaaa` o `aaaa-mm-dd`. Los estados y proveedores se validan contra sus catálogos. Un rango inválido se rechaza completo.
- **Guardar cambios** o Ctrl+S envía los cambios pendientes. **Deshacer** o Ctrl+Z revierte ediciones aún no guardadas; **Descartar** elimina los cambios pendientes tras confirmar. Salir, cambiar de master, filtrar o cambiar de página solicita confirmar si hay ediciones pendientes.
- Cada fila se guarda con control de versión. Si una fila falla, se conservan sus cambios y los de las filas aún no enviadas. Los conflictos y los guardados sin confirmación requieren **Recargar fila** antes de volver a editar esa fila. El conjunto de filas no es una transacción única.
- Cada columna se modifica de manera independiente. La BU ofrece M01, M19, M23, M45 y M46; la empresa y la referencia admiten captura manual. Corregir la referencia conserva el mismo embarque, sus documentos, provisiones, facturas e historial. Las referencias anteriores siguen localizándolo; la clasificación de transporte se actualiza al cambiar la operación.
- **Nuevo embarque** genera la referencia mediante el servidor. Abrir una referencia permite consultar o editar su detalle, incidencias y documentos.
- **Exportar página CSV** descarga las filas de la página visible, incluidos los cambios pendientes; no exporta el master completo ni un archivo XLSX. Se neutralizan valores que Excel podría interpretar como fórmulas. No se implementa cálculo de fórmulas ni importación de libros como masters; la carga del consolidado de facturación se realiza en su sección dedicada.

Los registros modificados permanecen visibles hasta actualizar o volver a aplicar los filtros.

![Master por responsable con datos de prueba locales](frontend/docs/masters-preview.png)

## Provisiones, facturas e historial

El menú principal incorpora **Provisiones**, **Facturas y conciliación** e **Historial**. La demostración incluye ejemplos financieros ficticios de octubre de 2026 y continúa siendo de solo lectura.

### Flujo financiero

1. Finanzas o Administración selecciona un mes y pulsa **Abrir periodo**. Esto crea un periodo abierto; no cierra ni reemplaza otros meses.
2. En **Provisiones**, busca o selecciona una referencia existente en la lista con responsable, BU y empresa (también admite flechas y Enter). Captura proveedor, concepto **FREIGHT**, **BROKER** o **STORAGE**, línea de costo, **fecha exacta**, moneda, importe neto y cargos extra. El mes de origen se deriva de la fecha y debe estar abierto. Guarda el borrador y pulsa **Aprobar**. Los borradores no afectan los saldos.
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

Esta versión requiere **0006_provision_date**, además de las migraciones anteriores; `0005_invoice_excel` conserva la evidencia original de la importación. No regeneres `.env`.

Con Docker, desde la raíz:

```powershell
git pull --ff-only origin main
docker compose build api migrate web
docker compose run --rm migrate
docker compose up -d api web
```

Con PostgreSQL sin Docker, detén los servicios, actualiza el repositorio y ejecuta `python -m alembic upgrade head` desde `backend` con el rol migrador. Después reinicia ambos servicios. Con SQLite local, detén la aplicación, respalda el archivo y actualiza el código; no ejecutes las migraciones PostgreSQL. Este primer esquema local se prepara automáticamente. Una futura actualización del esquema local debe incluir su procedimiento de migración; una versión incompatible detiene el inicio y conserva el archivo. Recarga el navegador con Ctrl+F5.

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

La migración `0006_provision_date` agrega la fecha exacta en PostgreSQL. La base SQLite local se actualiza automáticamente de la versión 1 a la 2 conservando sus filas. Las provisiones históricas sin día conocido conservan su mes y muestran «Día no registrado»; no se les atribuye una fecha inventada.

![Captura de provisión con fecha exacta y concepto](frontend/docs/provision-date-preview.png)
