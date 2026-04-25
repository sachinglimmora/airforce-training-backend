import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.middleware.audit import AuditMiddleware
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
from app.modules.scenarios.router import router as scenarios_router, simulations_router
from app.modules.analytics.router import router as analytics_router
from app.modules.competency.router import router as competency_router
from app.modules.vr_telemetry.router import router as vr_router
from app.modules.audit.router import router as audit_router
from app.modules.assets.router import router as assets_router
from app.modules.training.router import router as training_router
from app.modules.compatibility.router import router as compatibility_router
from app.modules.instructor.router import router as instructor_router
from app.modules.digital_twin.router import router as digital_twin_router
from app.modules.progress.router import router as progress_router
from app.modules.ai_assistant.router import router as ai_assistant_router
from app.modules.alerts.router import router as alerts_router
from app.modules.instructor_videos.router import router as instructor_videos_router
from app.modules.admin.router import router as admin_router

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

    # Audit logging for sensitive endpoints
    app.add_middleware(AuditMiddleware)

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
    app.include_router(simulations_router, prefix=f"{prefix}/simulations", tags=["simulations"])
    app.include_router(analytics_router, prefix=f"{prefix}/analytics", tags=["analytics"])
    app.include_router(competency_router, prefix=f"{prefix}", tags=["competency"])
    app.include_router(vr_router, prefix=f"{prefix}/vr", tags=["vr"])
    app.include_router(audit_router, prefix=f"{prefix}/audit", tags=["audit"])
    app.include_router(assets_router, prefix=f"{prefix}/assets", tags=["assets"])
    app.include_router(training_router, prefix=f"{prefix}", tags=["training"])
    app.include_router(compatibility_router, prefix=f"{prefix}", tags=["compatibility"])
    app.include_router(instructor_router, prefix=f"{prefix}/instructor", tags=["instructor"])
    app.include_router(digital_twin_router, prefix=f"{prefix}/digital-twin", tags=["digital-twin"])
    app.include_router(progress_router, prefix=f"{prefix}/progress", tags=["progress"])
    app.include_router(ai_assistant_router, prefix=f"{prefix}/ai-assistant", tags=["ai-assistant"])
    app.include_router(alerts_router, prefix=f"{prefix}/alerts", tags=["alerts"])
    app.include_router(instructor_videos_router, prefix=f"{prefix}/instructor-videos", tags=["instructor-videos"])
    app.include_router(admin_router, prefix=f"{prefix}/admin", tags=["admin"])

    # Health endpoints (no prefix — matched as /health)
    @app.get("/metrics", tags=["health"], include_in_schema=False)
    async def metrics():
        """Prometheus-format metrics. Restrict to internal network in production."""
        import os
        import time
        from app.core.health import check_readiness

        ready = await check_readiness()
        db_up = 1 if ready.get("database") == "ok" else 0
        redis_up = 1 if ready.get("redis") == "ok" else 0
        build_sha = os.environ.get("BUILD_SHA", "dev")

        lines = [
            "# HELP aegis_up Whether the service is up (1 = yes)",
            "# TYPE aegis_up gauge",
            "aegis_up 1",
            "# HELP aegis_db_up Whether the database is reachable (1 = yes)",
            "# TYPE aegis_db_up gauge",
            f"aegis_db_up {db_up}",
            "# HELP aegis_redis_up Whether Redis is reachable (1 = yes)",
            "# TYPE aegis_redis_up gauge",
            f"aegis_redis_up {redis_up}",
            f'# HELP aegis_build_info Build metadata',
            f'# TYPE aegis_build_info gauge',
            f'aegis_build_info{{version="1.0.0",sha="{build_sha}",env="{settings.ENV}"}} 1',
        ]
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

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
