# Operación local y despliegue Linux sin Docker

Los archivos de esta carpeta implementan el perfil productivo: API en `127.0.0.1:8000`, Nginx con HTTPS y frontend compilado, PostgreSQL corporativo con TLS y Microsoft Entra. El servicio se inicia con Linux y se reinicia si el proceso falla. No se ejecuta `ng serve` en producción.

## Inicio local en Windows

Desde la raíz del proyecto, después de cerrar cualquier sesión anterior que ocupe 4200 u 8000:

```bat
INICIAR_LOCAL.cmd
```

Conserva esa ventana abierta. Por defecto inicia la API real y Angular, crea `.data/masterlogistica.db` y permite editar con el usuario **Desarrollo local**. Los registros persisten al reiniciar. No requiere `.env.native`, un servidor de base de datos ni Entra. La plantilla `.env.native.example` permite cambiar catálogos o usar otra ruta SQLite absoluta.

Si ya existe `.env.native` con PostgreSQL/Entra, se conserva y sigue usando esa base de desarrollo; para elegir SQLite, guarda ese archivo como respaldo y usa la nueva plantilla. No se transfieren datos entre motores automáticamente. `DETENER_LOCAL.cmd`, `VER_ESTADO.cmd` y `VER_LOGS.cmd` controlan la sesión; `--demo` abre los ejemplos ficticios separados de la base local. Para respaldar SQLite, detén la aplicación y copia su archivo.

El inicio reutiliza Angular ya instalado y comprueba Node. Para un Python autorizado con los paquetes disponibles: `INICIAR_LOCAL.cmd --python "C:\ruta\python.exe" --skip-install`. También puedes iniciar `uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers` desde `backend` y `npm.cmd start` desde `frontend`, con el Python de `.venv`. No hay proceso worker. Consulta la [guía de inicio local](../../README.md#inicio-local-con-un-comando).

El modo SQLite solo admite loopback, sin proxy ni acceso desde otros equipos. **El servidor corporativo utiliza PostgreSQL y Entra**, con el perfil productivo que sigue. El paquete no incluye bases personales ni secretos. Esta separación simplifica el desarrollo local y mantiene el despliegue Linux sin Docker.

## 1. Preparar una entrega

En el entorno de construcción autorizado, con Node y las dependencias de `frontend` disponibles:

```bat
PREPARAR_ENTREGA.cmd
```

También funciona en Linux con `python3 scripts/build_release.py`. Siempre reconstruye Angular en producción, aunque se hayan ejecutado pruebas de navegador antes. Genera `.artifacts/masterlogistica-<id>.tar.gz` y su archivo `.sha256`. Incluye backend, migraciones, web compilada, plantillas y esta guía. No incluye `.env.native`, credenciales, `node_modules` ni el entorno Python de desarrollo.

Para una instalación sin Internet en el servidor, prepara las ruedas con **Linux, la misma arquitectura y versión menor de Python del destino**, en un entorno que pueda usar los repositorios autorizados:

```sh
python3 -m pip download --only-binary=:all: --require-hashes -r backend/requirements.lock --dest /ruta/wheelhouse
python3 scripts/build_release.py --wheelhouse /ruta/wheelhouse
```

No uses ruedas Windows para el servidor Linux. Como alternativa, el instalador admite `--online`, que utiliza la configuración de pip/proxy/CA autorizada por TI, o `--system-packages` si TI ya instaló exactamente los requisitos en el Python base. El modo predeterminado usa las ruedas incluidas y `--no-index`: no intenta conectarse a Internet.

La entrega se transporta mediante JE Git o el canal corporativo aprobado. El checksum comprueba integridad; se debe recibir por ese canal confiable. No se descarga ni ejecuta software desde Docker Hub.

## 2. Datos que debe proporcionar TI

| Dato | Uso |
| --- | --- |
| Nombre DNS interno | Host HTTPS, CORS y redirect URI SPA, todos con el mismo nombre |
| Servidor Linux y Python 3.11–3.14 | Nginx, systemd, soporte de venv y paquetes aprobados |
| Certificado HTTPS y clave | `/etc/masterlogistica/tls/fullchain.pem` y `privkey.pem`; clave solo accesible por la cuenta administradora del proxy |
| Endpoint PostgreSQL y base dedicada | El mismo endpoint/base para la API y las migraciones; sin apuntar a nodos individuales del clúster |
| Dos roles y sus secretos | `masterlogistica_app` restringido y `masterlogistica_migrator` para esquema/bootstrap |
| CA de PostgreSQL | `/etc/masterlogistica/postgres-ca.pem`, legible por ambas cuentas de servicio |
| Tenant/API/SPA Entra | Scope delegado `access_as_user`, tokens v2 y SPA HTTPS registrada |
| Catálogos | Compañías y BU aprobados; sin usar el catálogo ficticio de pruebas |

Las cuentas Linux `masterlogistica` y `masterlogistica-migrate` son cuentas de servicio separadas, sin login. Los scripts las crean si faltan; TI puede prepararlas antes dentro de su procedimiento. El proyecto no instala Nginx/Python desde repositorios públicos, no cambia reglas de firewall ni configura el clúster.

Para la base dedicada, el DBA puede revisar y ejecutar `prepare_database.sql` con el cliente `psql`, indicando el nombre esperado mediante `target_database`. No crea ni elimina bases, no fija contraseñas y no modifica los atributos de roles ya existentes. El DBA asigna las contraseñas por su mecanismo autorizado y comprueba que la API no sea dueña de tablas ni miembro del rol migrador. Crear ambos roles **antes** de Alembic permite aplicar sus permisos específicos.

## 3. Generar configuración

Una vez extraída la entrega en un directorio de preparación:

```sh
python3 deploy/linux/configure.py --domain NOMBRE-DNS-ASIGNADO --output /ruta/config-masterlogistica
```

Sustituye `NOMBRE-DNS-ASIGNADO` por el FQDN real, sin `https://`, puerto ni ruta. Se generan `api.env`, `migration.env`, `network.env`, `masterlogistica-api.service` y `masterlogistica.conf`. El generador no sobrescribe una carpeta con archivos.

Completa los `.env` con los datos de TI. Las contraseñas dentro de una URL deben estar codificadas como URL si contienen caracteres especiales. Las listas y los catálogos son JSON; por ejemplo `ENTRA_ALLOWED_CLIENT_IDS=["ID-DE-LA-SPA"]`. Esa SPA debe coincidir con `ENTRA_FRONTEND_CLIENT_ID`. `MIGRATION_DATABASE_URL` no se incluye en la configuración de API.

Si Entra requiere una CA corporativa adicional, configura su ruta absoluta en `ENTRA_CA_BUNDLE`. Se agrega a las raíces normales de confianza, sin desactivar la verificación TLS. Si se necesita proxy de salida, TI configura `HTTPS_PROXY` y `NO_PROXY` en el archivo separado `network.env`, que carga systemd. No coloques esas opciones dentro de `api.env`.

La topología preparada utiliza Nginx y API en el **mismo servidor**. Si TI termina TLS en otro equipo, debe adaptar la ruta de red y la confianza del proxy; no basta con poner la IP remota en una lista cuando la API escucha en loopback.

## 4. Instalar sin cambiar la versión activa

El administrador verifica la huella del archivo recibido antes de extraerlo en una carpeta vacía:

```sh
sha256sum -c masterlogistica-IDENTIFICADOR.tar.gz.sha256
mkdir entrega-masterlogistica
tar -xzf masterlogistica-IDENTIFICADOR.tar.gz -C entrega-masterlogistica
```

TI coloca primero los certificados y la CA en las rutas indicadas, mediante su procedimiento de certificados. Por ejemplo, con los archivos emitidos para el nombre DNS asignado:

```sh
sudo install -d -m 0755 /etc/masterlogistica/tls
sudo install -m 0644 /ruta/ca-postgresql.pem /etc/masterlogistica/postgres-ca.pem
sudo install -m 0644 /ruta/cadena-https.pem /etc/masterlogistica/tls/fullchain.pem
sudo install -m 0600 /ruta/clave-https.pem /etc/masterlogistica/tls/privkey.pem
```

Después, desde la carpeta de la entrega:

```sh
sudo env PYTHON_BIN=/usr/bin/python3.13 bash deploy/linux/install.sh /ruta/entrega-masterlogistica /ruta/config-masterlogistica
```

`PYTHON_BIN` debe ser el intérprete aprobado que exista en ese servidor; 3.13 es un ejemplo. Para usar el repositorio de paquetes configurado por TI, añade `--online` al final; para dependencias exactas ya instaladas en el Python base, añade `--system-packages`. No se desactiva TLS ni se cambia su política de certificados.

El instalador verifica el manifiesto, prepara `/opt/masterlogistica/releases/<id>/.venv`, copia los secretos solo si faltan y comprueba configuración, certificados y destino de los dos roles. Guarda los archivos de secretos con modo 0640 y grupos separados. Conserva la configuración existente en actualizaciones. Si falla la instalación, puede reintentarse con la misma entrega sin modificar el código ni el enlace activo. Si cambian las plantillas instaladas de Nginx/systemd, TI debe revisar esa diferencia antes de continuar.

Los secretos existentes se editan en `/etc/masterlogistica/` mediante el procedimiento de TI; modificar una copia de preparación no los sobrescribe en la siguiente instalación. Las cuentas de la aplicación no pueden modificar el código instalado.

## 5. Migrar y activar

En una ventana de mantenimiento, con respaldo y recuperación acordados con el DBA:

```sh
sudo bash /opt/masterlogistica/releases/IDENTIFICADOR/deploy/linux/activate.sh IDENTIFICADOR
```

La activación valida Nginx, los certificados, ambas conexiones, los roles y el destino de la base. Después detiene la API anterior, aplica Alembic con la cuenta migradora, verifica el esquema y cambia el enlace `current` a la entrega nueva. Inicia el servicio, espera `/health/ready` y recarga Nginx. No elimina datos, no regenera contraseñas y no restaura automáticamente un esquema anterior.

Si la migración falla, mantiene la API detenida y conserva el enlace anterior para revisión del DBA. Si falla un paso posterior a migrar, los scripts se detienen con error; revisar el estado antes de reiniciar. La recuperación del código anterior necesita comprobar compatibilidad con el esquema que quedó aplicado.

## 6. Aprovisionar el primer administrador

Después de migrar, el administrador autorizado ejecuta desde el backend de la entrega activa, con los identificadores aprobados:

```sh
cd /opt/masterlogistica/current/backend
sudo -u masterlogistica-migrate ../.venv/bin/python -m app.runtime bootstrap-admin --env-file /etc/masterlogistica/migration.env --object-id OBJECT-ID-ENTRA --email ADMINISTRADOR --display-name NOMBRE
```

`ENTRA_TENANT_ID` debe estar configurado también en `migration.env`. El bootstrap rechaza crear otro administrador si ya existe uno activo; el resto de usuarios se gestiona desde la API autenticada. Los códigos de analista y consecutivos iniciales se asignan únicamente después de contrastarlos con los registros de logística.

## 7. Verificar desde los equipos de usuarios

La URL de acceso es `https://NOMBRE-DNS-ASIGNADO/`. Desde una estación autorizada, usando el código del proyecto:

```bat
py -3 scripts\check_deployment.py https://NOMBRE-DNS-ASIGNADO
```

Si la CA HTTPS no está en el almacén de Python de esa estación, TI puede proporcionar su archivo y se indica con `--ca-file "C:\ruta\ca.pem"`. La comprobación verifica certificado, HTML y configuración pública de Entra; no sustituye la prueba de inicio de sesión con usuarios y roles reales.

Comprobar el acceso desde cada segmento requerido y el flujo de crear/consultar/importar con datos de piloto. Los usuarios necesitan TCP 443 al proxy; la API necesita el puerto PostgreSQL asignado y la salida Entra autorizada. No necesitan acceder a 4200, 8000 ni 5432 desde sus estaciones. Los endpoints `/health/` del proxy están limitados al propio host; un monitor remoto debe incorporarse mediante una regla aprobada.

## Operación y diagnóstico

```sh
systemctl status masterlogistica-api.service
journalctl -u masterlogistica-api.service -n 100 --no-pager
sudo nginx -t
```

Desde el backend activo, `../.venv/bin/python -m app.runtime check --env-file /etc/masterlogistica/api.env --database` valida conexión TLS, rol y versión del esquema con la cuenta de servicio. `--connection-only` sirve para comprobar conexión/rol antes de migrar sin exigir tablas todavía. Los comandos `check` no escriben datos. `/health/live` indica proceso vivo y `/health/ready` exige conexión y migraciones actuales; una caída de PostgreSQL devuelve indisponibilidad y el pool vuelve a comprobar las conexiones al recuperarse.

Los logs de la API omiten tokens, cuerpos de petición y URLs de conexión. Las comprobaciones de configuración no imprimen valores de secretos. Ante un timeout, revisar listener, DNS, certificado, proxy, rutas y firewall, siguiendo la guía `docs/DESPLIEGUE_EMPRESA.md`.

## Validación de esta configuración

Validación de esta actualización: 239 pruebas de backend (38 específicas del modo local SQLite), 29 pruebas de lanzadores/configuración, 42 casos existentes de navegador y una prueba completa con API/Angular reales. El inicio/cierre nativo conserva la base local. La entrega productiva se construyó y excluye SQLite y secretos; su manifiesto permite comprobar integridad.

El perfil productivo mantiene el smoke de Nginx/Uvicorn HTTPS en CI. En esta actualización no se ejecutó ese smoke aquí por faltar Nginx, ni las 39 pruebas de PostgreSQL nativo por faltar la base aislada. La configuración productiva exige PostgreSQL/Entra y rechaza la identidad local. Para el piloto sigue siendo necesaria la validación en el entorno autorizado.

Rollup queda fijado en 4.63.4 con dependencias opcionales Windows/Linux. Angular CLI se actualizó a 21.2.27 dentro de Angular 21; `npm audit` informó cero vulnerabilidades en esta revisión. Estas comprobaciones no sustituyen validar Application Control en el equipo corporativo ni Entra y el clúster reales. Las 39 pruebas de integración que requieren PostgreSQL externo están preparadas en CI y no se ejecutaron en este entorno de trabajo.
