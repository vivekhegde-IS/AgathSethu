"""
AGHAT SETHU — FastAPI Dependencies
Reusable dependencies injected into route handlers.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.models import User
from app.services.user_service import UserService

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Extract the current user from the JWT Bearer token.
    Raises HTTP 401 if the token is missing, invalid, or expired.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = UserService.get_by_id(db, user_id)
    if user is None:
        raise credentials_exception

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active",
        )

    return user


def require_authority(current_user: User = Depends(get_current_user)) -> User:
    """Require the current user to be authority or admin."""
    if current_user.role not in ("authority", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authority access required",
        )
    return current_user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require the current user to be admin."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
