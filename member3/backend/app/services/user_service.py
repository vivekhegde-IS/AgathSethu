"""
AGHAT SETHU — User Service
Handles user creation, lookup, and credential verification.
"""

from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.models import User
from app.schemas.schemas import CitizenRegisterRequest, AuthorityRegisterRequest


class UserService:

    @staticmethod
    def get_by_email(db: Session, email: str) -> User | None:
        """Retrieve a user by email address."""
        return db.query(User).filter(User.email == email.lower()).first()

    @staticmethod
    def get_by_id(db: Session, user_id: str) -> User | None:
        """Retrieve a user by UUID."""
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def email_exists(db: Session, email: str) -> bool:
        return db.query(User.id).filter(User.email == email.lower()).first() is not None

    @staticmethod
    def create_citizen(db: Session, data: CitizenRegisterRequest) -> User:
        """
        Create a new citizen user.
        Status is immediately 'active'.
        Password is hashed with bcrypt.
        """
        user = User(
            email=data.email.lower(),
            password_hash=hash_password(data.password),
            full_name=data.full_name.strip(),
            role="citizen",
            status="active",
            phone=data.phone,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def create_authority(db: Session, data: AuthorityRegisterRequest) -> User:
        """
        Create a new authority user.
        Status is 'pending_approval' — must be manually approved by admin.
        They CANNOT log in until status is changed to 'active'.
        """
        user = User(
            email=data.email.lower(),
            password_hash=hash_password(data.password),
            full_name=data.full_name.strip(),
            role="authority",
            status="pending_approval",
            badge_number=data.badge_number,
            jurisdiction=data.jurisdiction,
            phone=data.phone,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def authenticate(db: Session, email: str, password: str) -> User | None:
        """
        Verify email + password.
        Returns the user if credentials are correct and account is active.
        Returns None on any failure (wrong password, unknown email, inactive account).
        """
        user = UserService.get_by_email(db, email)
        if not user:
            return None

        # Always verify password (prevents timing attacks)
        if not verify_password(password, user.password_hash):
            return None

        # Enforce account status
        if user.status != "active":
            return None

        return user

    @staticmethod
    def authenticate_with_reason(db: Session, email: str, password: str) -> tuple[User | None, str]:
        """
        Like authenticate() but returns a reason string for better error messages.
        Returns (user, '') on success.
        Returns (None, reason) on failure.
        """
        user = UserService.get_by_email(db, email)
        if not user:
            return None, "Invalid email or password"

        if not verify_password(password, user.password_hash):
            return None, "Invalid email or password"

        if user.status == "pending_approval":
            return None, "Your account is pending approval. Please contact your administrator."

        if user.status == "suspended":
            return None, "Your account has been suspended. Please contact your administrator."

        if user.status != "active":
            return None, "Account is not active. Please contact support."

        return user, ""
