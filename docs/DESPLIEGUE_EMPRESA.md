# MasterLogistica: preparación del despliegue corporativo

Estado: el inicio local y las configuraciones del despliegue nativo están implementados; los pasos operativos están en [deploy/linux/README.md](../deploy/linux/README.md). La instalación en el servidor debe coordinarse con Infraestructura, Seguridad y DBA; esta guía no acredita un despliegue productivo ni una autorización de TI. Los datos de servidor, cuentas, dominio y clúster deben asignarse para MasterLogistica.

## Decisión con las tecnologías marcadas en rojo

El usuario identifica las tecnologías en rojo de la imagen proporcionada como las permitidas. Con esa referencia, la propuesta para este proyecto es **Angular + Python FastAPI + PostgreSQL + Microsoft Entra ID, en un servidor Linux interno, sin Docker**. Conserva el stack de la aplicación y cambia la forma de ejecutarlo en producción.

| Área | Elección para MasterLogistica |
| --- | --- |
| Frontend | Angular, compilado antes de publicar |
| Backend | Python FastAPI como servicio gestionado por Linux |
| Base de datos | PostgreSQL en el clúster autorizado, previa confirmación del DBA |
| Autenticación | Microsoft Entra ID SSO |
| Alojamiento | Servidor Linux interno |
| Código y entregas corporativas | JE Git, con el procedimiento de entrega definido por TI |

La imagen recomienda contenedores y el clúster AKS corporativo para aplicaciones que sirven a usuarios en varias regiones. La interpretación aplicada aquí es que esa recomendación tiene ese alcance; el texto no establece una obligación general de Docker para toda aplicación interna. Si MasterLogistica debe atender varias regiones, confirmar con Arquitectura la modalidad correspondiente antes de concretar el despliegue.

Azure aparece como una opción en preparación. Los servicios Azure enumerados en una pregunta de la imagen no se consideran disponibles o aprobados por esa sola mención. Las herramientas concretas de servicio y proxy web se elegirán dentro del estándar del servidor Linux asignado.

## Propósito y componentes

MasterLogistica es una aplicación interna de logística para gestionar embarques, referencias, documentos, provisiones, facturas e historial de cambios. Usa acceso Microsoft Entra y permisos por usuario y rol.

| Componente | Función |
| --- | --- |
| Angular | Interfaz web; se compila antes de publicar |
| FastAPI / Python | API y reglas de autorización y negocio |
| PostgreSQL | Datos operativos, conciliación, auditoría y migraciones |
| Nginx o proxy corporativo | HTTPS, frontend compilado y enrutamiento a la API |
| Microsoft Entra | Identidad corporativa y validación de tokens |

El desarrollo personal utiliza SQLite en un archivo local y no necesita Docker ni una cuenta Microsoft. Ese archivo no se utiliza como base compartida ni se transfiere automáticamente a producción.

El clúster debe ofrecer **PostgreSQL compatible con las migraciones de la aplicación**. Confirmar motor, versión y capacidades con el DBA. Un clúster SQL Server requeriría una adaptación del código y del esquema; cambiar solamente la cadena de conexión no basta. La referencia de desarrollo actual es PostgreSQL 17.

## Alternativas de ejecución

La propuesta inicial es **Linux con API como servicio y frontend compilado en el proxy web**, conectado al clúster corporativo. Permite desplegar sin Docker, Docker Hub, Docker Desktop ni WSL2. Infraestructura administra la cuenta de servicio, los paquetes aprobados, el arranque automático y los logs. FastAPI puede ejecutarse con Uvicorn y un gestor de servicios como systemd; no requiere contenedores. Node se usa al compilar el frontend; no se necesita para servir sus archivos compilados.

Si TI prefiere contenedores, usar **Docker Engine instalado directamente en Linux**, con Compose si lo aprueba su estándar. Los contenedores Linux de Engine no requieren una VM adicional dentro de Linux. Las imágenes deben llegar por el canal autorizado, preferentemente un registro corporativo si existe.

En ambos casos la base productiva pertenece al clúster administrado por el DBA. El `compose.yaml` del repositorio es de desarrollo: crea PostgreSQL local, usa `APP_ENV=development` y publica en loopback. Requiere una configuración productiva separada. `INICIAR_LOCAL.cmd` y su modo nativo tampoco instalan servicios de producción.

## Aprobación ITPM y responsabilidades

Según los antecedentes proporcionados por el responsable del proyecto, otro sistema necesitó ITPM y revisión de Seguridad para habilitar descargas. Preparar una solicitud específica para MasterLogistica y confirmar con TI el procedimiento vigente.

La solicitud debe incluir el propósito anterior, usuarios y áreas autorizadas, clasificación de datos, responsables de soporte, arquitectura elegida, inventario de software, origen de artefactos y matriz de conexiones. Las direcciones, cuentas y autorizaciones del sistema anterior no se toman como configuración de este proyecto.

| Responsable | Información o decisión requerida |
| --- | --- |
| Responsable funcional | Alcance, usuarios, datos y prueba de aceptación |
| Infraestructura | Linux y versión, servidor asignado, cuenta de servicio, proxy web, arranque y logs |
| Seguridad / ITPM | Modalidad de ejecución, software permitido y canales de distribución |
| Redes | DNS, segmentos autorizados, entrada HTTPS, salida y proxy corporativo |
| DBA | Endpoint PostgreSQL, base/esquema, roles, CA, migraciones, respaldo y recuperación |
| Administrador Entra | Registros API/SPA, permisos, URI HTTPS y usuarios iniciales |

Los cambios administrativos, credenciales, permisos y reglas del servidor deben quedar registrados en el procedimiento de TI y asociados a su responsable. Separar la cuenta de operación de la aplicación de la cuenta que instala o despliega. No publicar contraseñas, tokens, IP privadas ni datos operativos en tickets públicos o Git.

## Red de salida: paquetes, imágenes e identidad

El acceso a Docker Hub es independiente del acceso de los usuarios a la aplicación. Un servidor puede tener permiso para recibir HTTPS y seguir sin permiso para descargar imágenes.

Si se construyen las imágenes actuales del repositorio, se utilizan `python:3.13-slim`, `node:24-alpine` y `nginx:1.28-alpine`. El Compose local agrega `postgres:17`; la alternativa productiva con clúster no necesita ese contenedor. La construcción también descarga dependencias npm y Python. Registrar las versiones y los digest de la entrega aprobada; las etiquetas por sí solas pueden cambiar de contenido.

Para una salida controlada, TI puede proporcionar un registro de imágenes y repositorios de paquetes internos, o un canal aprobado de entrega de imágenes/paquetes ya construidos. El artefacto debe corresponder a la arquitectura y al sistema destino. La instalación inicial de Engine y sus actualizaciones también necesitan un origen aprobado.

Los dominios `registry-1.docker.io`, `auth.docker.io` y `production.cloudflare.docker.com` son antecedentes de otra solicitud, **no una lista exhaustiva garantizada**. TI debe validar los destinos actuales del producto, autenticación, descargas, CDN, proxy y certificados. La lista oficial de Docker Desktop sirve como referencia de ese producto, no como inventario completo de Engine, npm y Python. Configurar el proxy del daemon cuando corresponda: que el navegador o `curl` funcionen no demuestra que Docker tenga configurada la misma salida.

Los pulls anónimos siguen sujetos a las políticas corporativas y a las condiciones y límites del servicio. TI debe decidir si se usa una cuenta corporativa, un registro interno o entrega de artefactos. No usar cuentas personales ni cambiar DNS, proxy o validación TLS para eludir una restricción.

## Producto y licencias

Registrar el producto exacto: Docker Engine independiente en Linux y Docker Desktop son modalidades distintas. La documentación oficial identifica Engine como tecnología de código abierto y referencia Apache License 2.0. Docker Desktop tiene términos de suscripción propios, que incluyen condiciones de pago para uso profesional en organizaciones grandes.

La evaluación debe cubrir los productos realmente utilizados, las imágenes base, las dependencias, los servicios de registro y el soporte contratado. Código abierto no significa ausencia de licencia, obligaciones o costos de servicios. La documentación de Engine no acredita por sí sola que toda la solución tenga costo cero. Adjuntar el inventario y las licencias a la revisión de TI.

## Red de entrada y acceso al clúster

| Origen | Destino | Puerto previsto | Propósito |
| --- | --- | --- | --- |
| Estaciones de usuarios autorizados | Nombre DNS interno / proxy | TCP 443 | Aplicación por HTTPS |
| Proxy | API | TCP 8000 interno, o el asignado por TI | Peticiones `/api/`; sin acceso directo de usuarios |
| API y proceso de migración | Endpoint del clúster | TCP 5432 o el asignado por el DBA | PostgreSQL con TLS |
| Navegadores y API | Destinos aprobados de Microsoft Entra | TCP 443 | Inicio de sesión y claves públicas de validación |
| Entorno de construcción o despliegue | Registros/repositorios aprobados | TCP 443 normalmente | Imágenes, paquetes y actualizaciones |

Infraestructura debe confirmar dónde escucha el proxy, la interfaz/IP autorizada, las rutas, las reglas del host y las reglas entre segmentos. Puerto 80 solo si TI lo requiere, por ejemplo para redirigir a HTTPS. Las estaciones no necesitan acceso directo a PostgreSQL ni al puerto de la API. Si el proxy está en otro servidor, necesita una ruta de red autorizada hacia la API; un listener en `127.0.0.1` solo sirve para comunicación en ese mismo host.

**El Compose actual publica `127.0.0.1:4200`, `127.0.0.1:8000` y `127.0.0.1:5432`.** Está preparado para uso local. Para la publicación corporativa, el proxy debe exponer el nombre HTTPS autorizado y alcanzar el servicio interno. Abrir una regla de firewall no cambia la dirección en la que escucha el servicio.

Docker administra reglas de red propias. TI debe revisar la interacción con el firewall del host; una configuración de `ufw` por sí sola no acredita el alcance real de los puertos Docker. No deshabilitar firewalls ni exponer todos los puertos para probar conectividad.

## Diagnóstico: funciona en el servidor, falla desde Ingeniería

Un timeout como cURL 28 indica que una operación excedió su tiempo de espera; no identifica por sí solo qué firewall o componente falló. Comprobar por capas:

1. **Servicio:** proceso activo, logs y respuesta local de la API y del frontend. `/health/live` prueba vida del proceso; `/health/ready` comprueba conexión y versión de migraciones.
2. **Listener:** revisar la IP y el puerto con `ss -lnt`; si hay contenedores, revisar sus puertos publicados con la cuenta autorizada. Distinguir loopback de la interfaz de red corporativa.
3. **Proxy y TLS:** certificado válido y de confianza, nombre correcto, rutas `/api/` y encabezados del proxy. Verificar el archivo de configuración aplicado al servicio activo.
4. **DNS y recorrido desde la estación:** resolver el mismo nombre que usará el navegador y comprobar TCP 443 desde cada segmento de usuarios. TI revisa rutas, ACL y firewall local/perimetral.
5. **Aplicación:** con HTTPS accesible, comprobar Entra, redirect URI, usuario activo y permisos. Un HTTP 401/403 acredita una respuesta de algún componente, pero hay que identificar si proviene del proxy, de la API o de otra política.

Ejemplos de lectura, sustituyendo el nombre de ejemplo por el asignado por TI:

```sh
# En el servidor Linux; no cambia configuraciones.
ss -lnt
curl --connect-timeout 5 --max-time 10 -I https://logistica.example.invalid/
```

```powershell
# Desde una estación Windows autorizada.
Resolve-DnsName logistica.example.invalid
Test-NetConnection logistica.example.invalid -Port 443
curl.exe --connect-timeout 5 --max-time 10 -I https://logistica.example.invalid/
```

Registrar hora, estación/segmento de origen, nombre destino y resultado para el ticket interno. La prueba de aceptación debe hacerse desde las estaciones de usuarios, además del servidor.

## Permisos y administración de Docker

Si se elige Engine, TI debe asignar quién puede desplegar y operar el daemon. El grupo `docker` otorga privilegios equivalentes a root sobre el host. **No usar `chmod 666 /var/run/docker.sock`.** La solución es una política de operación aprobada, o rootless si TI lo selecciona y valida sus requisitos; no una apertura general del socket.

La cuenta del proceso de la API no necesita privilegios de administrador del servidor ni credenciales de migración. Mantener separados los permisos del host, los del daemon y los roles de PostgreSQL.

## Configuración productiva de la aplicación

Preparar la configuración fuera de Git y entregarla mediante el mecanismo de secretos autorizado:

- `APP_ENV=production`, Entra API/SPA y `ENTRA_ALLOWED_CLIENT_IDS` configurados.
- `DATABASE_URL` con el rol restringido `masterlogistica_app`, endpoint del clúster, `sslmode=verify-full` y la CA indicada por el DBA. No conectar desde la aplicación a nodos individuales si el DBA proporciona un endpoint de servicio/failover.
- `MIGRATION_DATABASE_URL` solo en el proceso separado que aplica migraciones. No se proporciona a la API productiva.
- `ENFORCE_HTTPS=true`, `ALLOWED_HOSTS` explícitos, `ALLOWED_ORIGINS` HTTPS y la URI de redirección SPA con el mismo nombre público.
- `COMPANY_CODES`, catálogo aprobado de `BUSINESS_UNITS` y usuarios/roles aprovisionados.

Al terminar TLS en un proxy, preparar y probar la propagación del esquema HTTPS y la confianza **solo en el proxy autorizado**. El perfil nativo implementado habilita los encabezados únicamente desde el proxy local configurado, que establece HTTPS explícitamente. El Dockerfile y el Compose conservan su configuración de desarrollo; no deben emplearse directamente como configuración productiva. El endpoint de salud y sus comprobaciones también deben funcionar con la configuración productiva de hosts y HTTPS.

El frontend compilado debe conservar el enrutamiento SPA y el proxy `/api/`. Mantener un límite de petición compatible con la importación XLSX: el Nginx actual permite 16 MB para el JSON base64 de archivos de hasta 10 MB. No subir secretos al frontend: los valores de una SPA son públicos para su usuario.

El clúster protege la disponibilidad de la base; también se necesitan soporte y recuperación de la API, el proxy y el servidor. Acordar monitoreo, respaldos, restauración y prueba de failover con el DBA.

## Secuencia propuesta de entrega

1. Completar y aprobar la solicitud ITPM/Seguridad, arquitectura, servidor, cuentas y matriz de red.
2. Confirmar compatibilidad PostgreSQL y recibir endpoint, CA, roles y base de desarrollo/piloto separados de la base operativa.
3. Construir y validar la versión por el canal autorizado. Entregar frontend compilado y backend/imagen, inventario de dependencias y versión exacta.
4. Preparar DNS, HTTPS, servicios y secretos. Configurar proxy y acceso al clúster. Obtener un respaldo y el procedimiento de reversión antes de migrar una instalación con datos.
5. Ejecutar `alembic upgrade head` con la identidad de migración; la versión actual incluye `0006_provision_date` (y `0005_invoice_excel` para la evidencia de importación). Iniciar API y frontend con sus identidades de operación.
6. Verificar salud, Entra, permisos por rol, captura/importación e historial con datos de prueba; comprobar acceso desde los segmentos de usuarios y recuperación después de reiniciar servicios.
7. Acordar ventana de puesta en servicio, responsables y soporte. Una reversión de código debe comprobar compatibilidad con el esquema; no borrar datos ni ejecutar una degradación automática del esquema.

Pendientes para concretar el despliegue: modalidad elegida por TI, distribución Linux y versiones aprobadas, host/DNS, cuenta de servicio, canal de artefactos, endpoint y motor del clúster, certificados, registros Entra, segmentos de usuarios y responsables de soporte. Las pruebas locales no acreditan estas condiciones corporativas.

## Fuentes y alcance de los antecedentes

Los incidentes de ITPM, Docker Hub, administración del servidor y acceso desde Ingeniería provienen del resumen proporcionado por el usuario sobre otro sistema. Se usan para preparar esta guía; no prueban la causa de una incidencia futura de MasterLogistica. Se omiten identificadores de personas, servidores y redes de ese sistema.

Referencias oficiales consultadas el 19 de octubre de 2026:

- [Docker Engine y licencia](https://docs.docker.com/engine/).
- [Términos de Docker Desktop](https://docs.docker.com/subscription-billing/desktop-license/).
- [Docker Desktop en VM/VDI y virtualización anidada](https://docs.docker.com/desktop/setup/vm-vdi/).
- [Red de salida: lista de Docker Desktop](https://docs.docker.com/desktop/enterprise/allow-list/) y [proxy del daemon Engine](https://docs.docker.com/engine/daemon/proxy/).
- [Publicación de puertos](https://docs.docker.com/engine/network/port-publishing/) y [Docker con firewalls de Linux](https://docs.docker.com/engine/network/packet-filtering-firewalls/).
- [Privilegios del grupo Docker](https://docs.docker.com/engine/install/linux-postinstall/) y [modo rootless](https://docs.docker.com/engine/security/rootless/).
- [Despliegue y gestión de procesos FastAPI](https://fastapi.tiangolo.com/deployment/concepts/) y [publicación de Angular compilado](https://angular.dev/tools/cli/deployment).
