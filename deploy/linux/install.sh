#!/usr/bin/env bash
# Run by the authorized server administrator. This step does not activate the release.
set -Eeuo pipefail
export PYTHONDONTWRITEBYTECODE=1

fail() { echo "ERROR: $*" >&2; exit 1; }
[[ "$EUID" -eq 0 ]] || fail "Ejecuta la instalacion con la cuenta administradora autorizada."
[[ "$#" -ge 2 ]] || fail "Uso: bash install.sh DIRECTORIO_ENTREGA DIRECTORIO_CONFIG [--online|--system-packages]"
release_source="$(realpath "$1")"
config_source="$(realpath "$2")"
install_mode="${3:-offline}"
case "$install_mode" in offline|--online|--system-packages) ;; *) fail "Opcion de instalacion no valida." ;; esac
python_bin="${PYTHON_BIN:-python3}"
"$python_bin" -c 'import sys; assert (3,11) <= sys.version_info < (3,15)' || fail "Se necesita Python 3.11 a 3.14 autorizado."
for program in runuser useradd install systemctl nginx cmp; do
    command -v "$program" >/dev/null || fail "Falta $program. Solicita el paquete aprobado a TI."
done
[[ ! -e "$release_source/.venv" ]] || fail "La entrega de entrada no debe incluir un entorno Python."
release_id="$("$python_bin" "$release_source/deploy/linux/release.py" "$release_source")"
release_target="/opt/masterlogistica/releases/$release_id"
for filename in api.env migration.env masterlogistica-api.service masterlogistica.conf; do
    [[ -f "$config_source/$filename" ]] || fail "Falta $filename. Ejecuta configure.py primero."
done
if [[ "$install_mode" == offline ]]; then
    [[ -d "$release_source/wheels" ]] || fail "Faltan ruedas Linux. Incluye --wheelhouse al crear la entrega o usa el canal de paquetes autorizado con --online."
fi
# A previous production configuration is never overwritten during an upgrade.
for item in "masterlogistica-api.service:/etc/systemd/system/masterlogistica-api.service" "masterlogistica.conf:/etc/nginx/conf.d/masterlogistica.conf"; do
    source_name="${item%%:*}"
    destination="${item#*:}"
    if [[ -e "$destination" ]] && ! cmp -s "$config_source/$source_name" "$destination"; then
        fail "La plantilla $source_name cambio. TI debe revisar e instalar esa configuracion antes de continuar."
    fi
done
for account in masterlogistica masterlogistica-migrate; do
    if ! id "$account" >/dev/null 2>&1; then
        useradd --system --user-group --home-dir /nonexistent --shell "$(command -v nologin)" "$account"
    fi
    [[ "$(id -u "$account")" != 0 ]] || fail "La cuenta de servicio no puede ser root."
    getent group "$account" >/dev/null || fail "Falta el grupo de servicio $account."
done
install -d -m 0755 /opt/masterlogistica/releases /etc/masterlogistica /etc/masterlogistica/tls
if [[ ! -e "$release_target" ]]; then
    install -d -m 0755 "$release_target"
    cp -R "$release_source/." "$release_target/"
    chown -R root:root "$release_target"
    chmod -R go-w "$release_target"
fi
"$python_bin" "$release_target/deploy/linux/release.py" "$release_target" >/dev/null
if [[ "$install_mode" == --system-packages ]]; then
    "$python_bin" -m venv --system-site-packages "$release_target/.venv"
else
    "$python_bin" -m venv "$release_target/.venv"
fi
release_python="$release_target/.venv/bin/python"
if [[ "$install_mode" == --online ]]; then
    # Uses the administrator's approved pip/proxy/CA configuration. Never disables TLS.
    "$release_python" -m pip install --require-hashes -r "$release_target/backend/requirements.lock"
else
    "$release_python" -m pip install --no-index --find-links "$release_target/wheels" --require-hashes -r "$release_target/backend/requirements.lock"
fi
for role in api migration network; do
    account=masterlogistica
    [[ "$role" == migration ]] && account=masterlogistica-migrate
    if [[ ! -e "/etc/masterlogistica/$role.env" ]]; then
        [[ -f "$config_source/$role.env" ]] || continue
        install -o root -g "$account" -m 0640 "$config_source/$role.env" "/etc/masterlogistica/$role.env"
    fi
done
install -m 0644 "$config_source/masterlogistica-api.service" /etc/systemd/system/masterlogistica-api.service
install -m 0644 "$config_source/masterlogistica.conf" /etc/nginx/conf.d/masterlogistica.conf
cd "$release_target/backend"
runuser -u masterlogistica -- "$release_python" -m app.runtime check --env-file /etc/masterlogistica/api.env
runuser -u masterlogistica-migrate -- "$release_python" -m app.runtime check --migration --env-file /etc/masterlogistica/migration.env
"$release_python" -m app.runtime check --env-file /etc/masterlogistica/api.env --migration-env-file /etc/masterlogistica/migration.env
echo "Entrega preparada: $release_id. La version activa y los datos se conservaron."
echo "Siguiente paso: bash $release_target/deploy/linux/activate.sh $release_id"
