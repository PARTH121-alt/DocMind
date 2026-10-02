"""Shared FastAPI dependencies: authentication, rate limiting, pagination."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.core.security_utils import check_rate_limit
from app.models.entities import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user or reject the request."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    subject = decode_access_token(credentials.credentials)
    if not subject:
        raise unauthorized
    user = await db.get(User, subject)
    if user is None or not user.is_active:
        raise unauthorized
    return user


async def rate_limited(request: Request, user: User = Depends(get_current_user)) -> User:
    """Per-user request budget applied to expensive endpoints."""
    scope = f"{user.id}:{request.url.path.rsplit('/', 1)[0]}"
    check_rate_limit(scope, settings.rate_limit_requests, settings.rate_limit_window_seconds)
    return user


class Pagination:
    def __init__(self, page: int = 1, page_size: int = 25) -> None:
        self.page = max(1, page)
        self.page_size = min(100, max(1, page_size))

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size
