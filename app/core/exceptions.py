from fastapi import HTTPException, status


class AegisException(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, details: list | None = None):
        super().__init__(status_code=status_code)
        self.code = code
        self.message = message
        self.details = details or []


class InvalidCredentials(AegisException):
    def __init__(self):
        super().__init__(status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS", "Invalid email or password")


class TokenExpired(AegisException):
    def __init__(self):
        super().__init__(status.HTTP_401_UNAUTHORIZED, "TOKEN_EXPIRED", "Access token has expired")


class TokenInvalid(AegisException):
    def __init__(self):
        super().__init__(status.HTTP_401_UNAUTHORIZED, "TOKEN_INVALID", "Token signature or structure is invalid")


class TokenRevoked(AegisException):
    def __init__(self):
        super().__init__(status.HTTP_401_UNAUTHORIZED, "TOKEN_REVOKED", "Refresh token has been revoked")


class Forbidden(AegisException):
    def __init__(self, message: str = "You do not have permission to perform this action"):
        super().__init__(status.HTTP_403_FORBIDDEN, "FORBIDDEN", message)


class PIIDetected(AegisException):
    def __init__(self):
        super().__init__(status.HTTP_403_FORBIDDEN, "PII_DETECTED", "Request blocked: personal data detected")


class NotFound(AegisException):
    def __init__(self, resource: str = "Resource"):
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", f"{resource} not found")


class Conflict(AegisException):
    def __init__(self, message: str = "Resource already exists"):
        super().__init__(status.HTTP_409_CONFLICT, "CONFLICT", message)


class AccountLocked(AegisException):
    def __init__(self):
        super().__init__(423, "ACCOUNT_LOCKED", "Account locked due to too many failed login attempts")


class RateLimited(AegisException):
    def __init__(self):
        super().__init__(status.HTTP_429_TOO_MANY_REQUESTS, "RATE_LIMITED", "Rate limit exceeded")


class TooManyAttempts(AegisException):
    def __init__(self):
        super().__init__(status.HTTP_429_TOO_MANY_REQUESTS, "TOO_MANY_ATTEMPTS", "Too many login attempts")


class CitationNotFound(AegisException):
    def __init__(self, key: str):
        super().__init__(status.HTTP_400_BAD_REQUEST, "CITATION_NOT_FOUND", f"Citation key not found: {key}")


class AllProvidersDown(AegisException):
    def __init__(self):
        super().__init__(status.HTTP_502_BAD_GATEWAY, "ALL_PROVIDERS_DOWN", "All AI providers are currently unavailable")


class ValidationFailed(AegisException):
    def __init__(self, details: list):
        super().__init__(status.HTTP_400_BAD_REQUEST, "VALIDATION_FAILED", "Request validation failed", details)
