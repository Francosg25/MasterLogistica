#!/usr/bin/env bash
# Explicit maintenance operation: migrations, atomic release selection and service restart.
set -Eeuo pipefail
export PYTHONDONTWRITEBYTECODE=1
fail() { echo "ERROR: $*" >&2; exit 1; }
[[ "$EUID" -eq 0 ]] || fail "Usa la cuenta administradora autorizada."
[[ "${1:-}" =~ ^[a-f0-9]{16}$ ]] || fail "Indica el identificador de la entrega preparada."
release_target="/opt/masterlogistica/releases/$1"
release_python="$release_target/.venv/bin/python"
[[ -x "$release_python" ]] || fail "La entrega no tiene un entorno Python preparado."
"$release_python" "$release_target/deploy/linux/release.py" "$release_target" >/dev/null
[[ ! -e /opt/masterlogistica/current || -L /opt/masterlogistica/current ]] || fail "current debe ser un enlace administrado de entrega."
cd "$release_target/backend"
# All non-mutating checks precede the maintenance window.
nginx -t
"$release_python" -m app.runtime check --env-file /etc/masterlogistica/api.env --migration-env-file /etc/masterlogistica/migration.env
runuser -u masterlogistica -- "$release_python" -m app.runtime check --env-file /etc/masterlogistica/api.env --database --connection-only
runuser -u masterlogistica-migrate -- "$release_python" -m app.runtime check --env-file /etc/masterlogistica/migration.env --migration --database
echo "Iniciando mantenimiento. Debe existir un respaldo y procedimiento de recuperacion acordados con el DBA."
systemctl daemon-reload
systemctl stop masterlogistica-api.service
if ! runuser -u masterlogistica-migrate -- "$release_python" -m app.runtime migrate --env-file /etc/masterlogistica/migration.env; then
    fail "La migracion fallo. API detenida y enlace anterior conservado; revisar con el DBA antes de reiniciar."
fi
runuser -u masterlogistica -- "$release_python" -m app.runtime check --env-file /etc/masterlogistica/api.env --database
next_link="/opt/masterlogistica/.next-$$"
trap 'rm -f "$next_link"' EXIT
ln -s "$release_target" "$next_link"
mv -Tf "$next_link" /opt/masterlogistica/current
systemctl daemon-reload
systemctl enable masterlogistica-api.service
systemctl restart masterlogistica-api.service
runuser -u masterlogistica -- "$release_python" -m app.runtime probe --env-file /etc/masterlogistica/api.env --timeout 60
nginx -t
if systemctl is-active --quiet nginx; then
    systemctl reload nginx
else
    systemctl enable --now nginx
fi
echo "Entrega activada: $1. Verifica HTTPS, Entra y acceso desde las estaciones autorizadas."
