"""FastAPI dependency that validates JWT tokens on every protected request."""
import os
import sys

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from services.api_gateway.auth import decode_token  # noqa: E402

log = structlog.get_logger()

security = HTTPBearer(auto_error=False)

# Paths that do not require a token
_PUBLIC_PATHS: tuple[str, ...] = (
    "/health",
    "/api/auth/login",
    "/api/auth/register",
)
_PUBLIC_PREFIXES: tuple[str, ...] = ()


async def get_current_engineer(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """Validate the Bearer token and return the caller's identity.

    Skips authentication for /health and /api/auth/* paths so that login
    and registration endpoints remain publicly accessible.

    Returns:
        Dict with engineer_id (email) and role.

    Raises:
        HTTPException 401 for missing or invalid tokens on protected paths.
    """
    path = request.url.path

    if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return {"engineer_id": None, "role": None}

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials)
        engineer_id: str = payload["sub"]
        role: str = payload["role"]
    except (JWTError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    request.state.engineer_id = engineer_id
    request.state.role = role

    log.info("auth.validated", engineer_id=engineer_id, path=path)
    return {"engineer_id": engineer_id, "role": role}
