# MasterLogistica

Aplicación de control de embarques. Incluye backend FastAPI/PostgreSQL y el primer bloque de Masters en Angular 21: acceso Microsoft, consulta, filtros, alta, edición y documentos por operación.

## Estado

- Referencias: nomenclatura versionada y catálogo de BU configurable.
- Masters: selección obligatoria de responsable y tipo de operación; búsqueda, paginación e indicadores limitados al master seleccionado. Los cinco integrantes de logística conservan masters individuales.
- Detalle: edición con control de concurrencia, pedimentos, BL, contenedores, guías y seguimiento de incidencias.
- Demostración: disponible sin credenciales, con datos ficticios y sólo lectura. No consulta ni modifica registros operativos.
- Pendiente: importación de Excel, provisiones aprobadas/rolling, facturas y conciliación. La validación con PostgreSQL, Docker y Microsoft Entra ID real todavía debe realizarse en el entorno autorizado.

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

Verificación local de este bloque: **165 pruebas de backend aprobadas, 18 de integración pendientes por falta de PostgreSQL, y 14 pruebas de navegador aprobadas**. El build de producción compila correctamente.

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

La interfaz organiza el trabajo como un registro de movimientos: navegación compacta, vistas por estado, indicadores en una franja y ficha lateral de operación. Usa fondo marfil, acento naranja y tipografía editorial.

![Masters con datos ficticios](frontend/docs/masters-preview.png)
