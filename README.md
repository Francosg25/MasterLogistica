# MasterLogistica

Proyecto de control de embarques, provisiones y auditoría de facturación. El backend de Fase 2 está implementado; la validación con PostgreSQL, Docker y las aplicaciones de identidad reales está pendiente.

## Desarrollo local

Requisitos: Python 3.11+ y Docker Compose v2.

```bash
python scripts/configure_local.py
docker compose up --build -d
```

En Windows: `py -3.13 scripts/configure_local.py`.

Documentación de API de desarrollo: http://127.0.0.1:8000/docs

## Verificación

127 pruebas locales pasan. La suite contiene además 15 pruebas de integración que requieren una base PostgreSQL desechable. El workflow de [GitHub Actions](.github/workflows/backend.yml) prepara esas verificaciones y el arranque con Docker.

No se ha implementado frontend, arrastre mensual o procesamiento de facturas en esta fase. Los archivos operativos y las credenciales quedan fuera del repositorio.
