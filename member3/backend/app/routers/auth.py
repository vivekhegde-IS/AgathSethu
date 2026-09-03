"""
AGHAT SETHU — Auth Router
Handles registration, login, /me, and logout.

Base prefix: /api/auth  (configured in main.py)
So individual paths here are: /register, /login, /me, /logout
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token
from app.dependencies.deps import get_current_user
from app.models.models import User
from app.schemas.schemas import (
    AuthorityRegisterRequest,
    CitizenRegisterRequest,
    LoginRequest,
    MessageResponse,
    RegisterResponse,
    TokenResponse,
    UserResponse,
)
from app.services.user_service import UserService

router = APIRouter()


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description=(
        "Register a citizen (status=active) or authority (status=pending_approval). "
        "Pass `role=citizen` or `role=authority` in the query parameter."
    ),
)
def register(
    role: str,
    db: Session = Depends(get_db),
    citizen_data: CitizenRegisterRequest | None = None,
    authority_data: AuthorityRegisterRequest | None = None,
):
    """
    NOTE: Role-specific register endpoints are cleaner.
    This generic endpoint is kept for future flexibility.
    Use /register/citizen or /register/authority instead.
    """
    raise HTTPException(
        status_code=400,
        detail="Use /api/auth/register/citizen or /api/auth/register/authority",
    )


@router.post(
    "/register/citizen",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new citizen account",
)
def register_citizen(data: CitizenRegisterRequest, db: Session = Depends(get_db)):
    """
    Register a citizen account.
    - Account is immediately active.
    - Password is hashed with bcrypt.
    - Returns user_id and status confirmation.
    """
    if UserService.email_exists(db, data.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = UserService.create_citizen(db, data)
    return RegisterResponse(
        message="Registration successful. You can now log in.",
        user_id=str(user.id),
        status=user.status,
    )


@router.post(
    "/register/authority",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request authority / officer account",
)
def register_authority(data: AuthorityRegisterRequest, db: Session = Depends(get_db)):
    """
    Submit an authority account request.
    - Account status is set to 'pending_approval'.
    - Officer CANNOT log in until an admin activates the account.
    - Returns confirmation — does NOT issue a JWT.
    """
    if UserService.email_exists(db, data.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = UserService.create_authority(db, data)
    return RegisterResponse(
        message=(
            "Your clearance request has been submitted successfully. "
            "An administrator will review and activate your account. "
            "You will be notified once access is granted."
        ),
        user_id=str(user.id),
        status=user.status,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and receive JWT",
)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """
    Login endpoint.
    - Verifies email + password against bcrypt hash in PostgreSQL.
    - Enforces account status (pending/suspended accounts are rejected).
    - Returns a signed JWT access token and basic user info.
    """
    user, reason = UserService.authenticate_with_reason(db, data.email, data.password)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=reason or "Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
        }
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user",
)
def get_me(current_user: User = Depends(get_current_user)):
    """
    Returns the profile of the currently authenticated user.
    Requires a valid Bearer JWT in the Authorization header.
    This endpoint validates that the token is still valid and the account is active.
    """
    return UserResponse.model_validate(current_user)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout (stateless — clears frontend token)",
)
def logout():
    """
    Stateless logout endpoint.

    IMPORTANT: Standard JWT tokens are stateless — this endpoint does NOT
    invalidate the token on the server side (no revocation mechanism implemented
    in Phase 1). The frontend should:
    1. Remove the token from localStorage.
    2. Clear Zustand auth state.
    3. Navigate to "/".

    This endpoint exists for API consistency and future revocation support.
    """
    return MessageResponse(message="Logged out successfully. Please clear your local session.")
