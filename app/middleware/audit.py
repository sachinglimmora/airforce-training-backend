"""Audit middleware — logs sensitive endpoint access to the audit_log table."""
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger()

# Exact-match path → action label
_EXACT: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/auth/login"): "auth.login",
    ("POST", "/api/v1/auth/refresh"): "auth.token_refresh",
    ("POST", "/api/v1/auth/logout"): "auth.logout",
    ("POST", "/api/v1/auth/change-password"): "auth.password_changed",
    ("POST", "/api/v1/users"): "user.created",
    ("POST", "/api/v1/content/sources"): "content.uploaded",
    ("POST", "/api/v1/ai/complete"): "ai.query",
    ("POST", "/api/v1/ai/embed"): "ai.query",
}

# Prefix-match (method, prefix) → action label — checked if exact misses
_PREFIX: list[tuple[tuple[str, str], str]] = [
    (("DELETE", "/api/v1/users/"), "user.deleted"),
    (("POST", "/api/v1/users/"), "user.role_assigned"),
    (("POST", "/api/v1/content/sources/"), "content.action"),
    (("GET", "/api/v1/audit/"), "data.accessed"),
]


def _resolve_action(method: str, path: str) -> str | None:
    action = _EXACT.get((method, path))
    if action:
        return action
    for (m, prefix), act in _PREFIX:
        if method == m and path.startswith(prefix):
            return act
    return None


def _extract_user_id(request: Request) -> str | None:
    try:
        from app.core.security import decode_access_token
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            payload = decode_access_token(auth[7:])
            return payload.get("sub")
    except Exception:
        pass
    return None


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        action = _resolve_action(request.method, request.url.path)
        if action is None:
            return response

        status = response.status_code
        if status < 400:
            outcome = "success"
        elif status in (401, 403):
            outcome = "denied"
        else:
            outcome = "error"

        actor_id = _extract_user_id(request)
        ip = request.client.host if request.client else None
        path_parts = request.url.path.split("/")
        resource_type = path_parts[3] if len(path_parts) > 3 else None
        resource_id = path_parts[4] if len(path_parts) > 4 else None

        from app.database import AsyncSessionLocal
        from app.modules.audit.service import AuditService

        async with AsyncSessionLocal() as db:
            try:
                svc = AuditService(db)
                await svc.log(
                    action=action,
                    actor_user_id=actor_id,
                    actor_ip=ip,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    outcome=outcome,
                )
                await db.commit()
            except Exception as exc:
                log.warning("audit_middleware_error", error=str(exc))

        return response
