import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import router
from app.auth import EntraTokenValidator
from app.config import Settings
from app.db import build_engine, build_session_factory
from app.finance import router as finance_router
from app.invoice_import import router as import_router
from app.observability import RequestLoggingMiddleware, logger
from app.reference_families import router as families_router


def create_app(
    settings: Settings | None = None, key_resolver: Callable[[str], Any] | None = None
) -> FastAPI:
    settings = settings or Settings()
    engine = build_engine(settings)
    heads = set(
        ScriptDirectory(str(Path(__file__).resolve().parent.parent / "migrations")).get_heads()
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            if settings.auth_mode == "development":
                from app.local_schema import initialize_local

                Path(make_url(settings.database_url.get_secret_value()).database).parent.mkdir(
                    parents=True, exist_ok=True
                )
                initialize_local(engine, app.state.session_factory)
            yield
        finally:
            engine.dispose()

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    app = FastAPI(
        title="MasterLogistica API",
        version="0.2.0",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.token_validator = (
        EntraTokenValidator(settings, key_resolver) if settings.auth_mode == "entra" else None
    )
    app.include_router(router)
    app.include_router(families_router)
    app.include_router(finance_router)
    app.include_router(import_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        allow_credentials=False,
    )
    if settings.enforce_https:
        app.add_middleware(HTTPSRedirectMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    if settings.auth_mode == "development":
        from app.local_access import LocalAccessMiddleware

        app.add_middleware(LocalAccessMiddleware, origins=settings.allowed_origins)
    app.add_middleware(RequestLoggingMiddleware)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Do not echo Pydantic input/ctx, which may contain sensitive form values.
        safe_errors = [
            {"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": safe_errors})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Database operation temporarily unavailable",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Unexpected server error",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.get("/health/live", tags=["Health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"])
    def ready(request: Request):
        try:
            with request.app.state.engine.connect() as connection:
                if settings.auth_mode == "development":
                    from app.local_schema import check_local_schema

                    if not check_local_schema(connection):
                        raise HTTPException(503, "Local database schema is not current")
                else:
                    versions = set(
                        connection.scalars(text("SELECT version_num FROM alembic_version"))
                    )
                    if versions != heads:
                        raise HTTPException(503, "Database migration version is not current")
        except SQLAlchemyError:
            raise HTTPException(503, "Database or migrations unavailable") from None
        return {"status": "ready"}

    return app


def __getattr__(name):
    # Support uvicorn app.main:app without loading ambient .env/settings when
    # the production runtime imports only create_app with explicit configuration.
    if name == "app":
        return create_app()
    raise AttributeError(name)
