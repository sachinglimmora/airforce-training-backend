import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.middleware.error_handler import add_error_handlers
from app.middleware.rate_limit import RateLimitMiddleware
from app.openapi_tags import tags_metadata

# Module routers
from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.content.router import router as content_router
from app.modules.ai.router import router as ai_router
from app.modules.checklist.router import router as checklist_router
from app.modules.procedures.router import router as procedures_router
from app.modules.scenarios.router import router as scenarios_router
from app.modules.analytics.router import router as analytics_router
from app.modules.competency.router import router as competency_router
from app.modules.vr_telemetry.router import router as vr_router
from app.modules.audit.router import router as audit_router
from app.modules.assets.router import router as assets_router

log = structlog.get_logger()
settings = get_settings()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Aegis Aerospace Training API",
        version="1.0.0",
        description="Backend API for Glimmora Aegis Aerospace training platform",
        openapi_tags=tags_metadata,
        docs_url="/api/v1/docs" if not settings.is_production else None,
        redoc_url="/api/v1/redoc" if not settings.is_production else None,
        openapi_url="/api/v1/openapi.json",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    app.add_middleware(RateLimitMiddleware)

    # Global error handlers
    add_error_handlers(app)

    # Routers
    prefix = "/api/v1"
    app.include_router(auth_router, prefix=f"{prefix}/auth", tags=["auth"])
    app.include_router(users_router, prefix=f"{prefix}", tags=["users"])
    app.include_router(content_router, prefix=f"{prefix}/content", tags=["content"])
    app.include_router(ai_router, prefix=f"{prefix}/ai", tags=["ai"])
    app.include_router(checklist_router, prefix=f"{prefix}/checklists", tags=["checklists"])
    app.include_router(procedures_router, prefix=f"{prefix}/procedures", tags=["procedures"])
    app.include_router(scenarios_router, prefix=f"{prefix}/scenarios", tags=["scenarios"])
    app.include_router(analytics_router, prefix=f"{prefix}/analytics", tags=["analytics"])
    app.include_router(competency_router, prefix=f"{prefix}", tags=["competency"])
    app.include_router(vr_router, prefix=f"{prefix}/vr", tags=["vr"])
    app.include_router(audit_router, prefix=f"{prefix}/audit", tags=["audit"])
    app.include_router(assets_router, prefix=f"{prefix}/assets", tags=["assets"])

    # Health endpoints (no prefix — matched as /health)
    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def readiness():
        from app.core.health import check_readiness
        return await check_readiness()

    @app.get("/version", tags=["health"])
    async def version():
        import os
        return {
            "version": "1.0.0",
            "env": settings.ENV,
            "build_sha": os.environ.get("BUILD_SHA", "dev"),
        }

    @app.on_event("startup")
    async def startup():
        log.info("aegis_backend_started", env=settings.ENV)

    @app.on_event("shutdown")
    async def shutdown():
        log.info("aegis_backend_stopped")

    return app


app = create_app()
