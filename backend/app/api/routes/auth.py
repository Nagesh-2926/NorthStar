import hmac
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.app.core.dependencies import get_current_user
from backend.app.core.security import create_access_token, hash_password, verify_password
from backend.app.db.dependencies import get_db
from backend.app.models import Student, User
from backend.app.schemas.common import (LoginRequest, PasswordChangeRequest, TokenRead,
    UserCreate, UserRead, UserRole)
from ml.identity_registry import allocate_application_enrollment_number

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    role = body.role.value
    if body.role == UserRole.COORDINATOR:
        invite = settings.coordinator_invite_code
        if invite is None or body.invite_code is None or not hmac.compare_digest(
                body.invite_code, invite.get_secret_value()):
            raise HTTPException(status_code=403, detail="Coordinator registration is invite-only")
    email = str(body.email).lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(email=email, password_hash=hash_password(body.password), role=role)
    db.add(user)
    try:
        db.flush()
        if role == "student":
            student = Student(user_id=user.id, access_approved=False)
            db.add(student)
            db.flush()
            student.enrollment_number = allocate_application_enrollment_number(
                student.id, settings.application_enrollment_registry_path
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account could not be created with these details") from exc
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenRead)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = str(body.email).lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")
    settings = request.app.state.settings
    expires = settings.access_token_expire_minutes
    token = create_access_token(str(user.id), user.role,
        settings.jwt_secret_key.get_secret_value(), expires, settings.jwt_algorithm,
        token_version=user.token_version)
    return TokenRead(access_token=token, expires_in=expires * 60)


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password")
def change_password(body: PasswordChangeRequest, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Choose a password different from the current password")
    result = db.execute(update(User).where(
        User.id == user.id, User.token_version == user.token_version
    ).values(password_hash=hash_password(body.new_password),
             token_version=User.token_version + 1))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account changed during this request. Sign in again and retry.")
    db.commit()
    return {"message": "Password updated. Sign in again with your new password."}
