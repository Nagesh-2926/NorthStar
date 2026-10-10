from collections.abc import Callable
from uuid import UUID
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from backend.app.db.dependencies import get_db
from backend.app.models import Student, User

bearer = HTTPBearer(auto_error=False)


def get_current_user(request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    settings = request.app.state.settings
    try:
        claims = jwt.decode(credentials.credentials, settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm], options={"require": ["exp", "sub", "type"]})
        if claims.get("type") != "access":
            raise unauthorized
        user_id = UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise unauthorized
    user = db.get(User, user_id)
    if (user is None or not user.is_active or claims.get("role") != user.role
            or claims.get("ver", 0) != user.token_version):
        raise unauthorized
    return user


def require_roles(*roles: str) -> Callable:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return dependency


def get_authorized_student(student_id: UUID, user: User, db: Session) -> Student:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    if user.role == "student" and student.user_id != user.id:
        # Hide cross-account resource existence from students.
        raise HTTPException(status_code=404, detail="Student not found")
    if user.role == "student" and not student.access_approved:
        raise HTTPException(status_code=403,
                            detail="Student access requires coordinator approval.")
    return student
