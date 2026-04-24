"""Audit middleware — writes structured audit entries via AuditService."""
from starlette.middleware.base import BaseHTTPMiddleware

# Audit writes happen inside route handlers via AuditService; this module is
# reserved for cross-cutting audit concerns (e.g. sensitive-read tagging).
