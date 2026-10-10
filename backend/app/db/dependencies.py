from collections.abc import Generator
from fastapi import Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Generator[Session, None, None]:
    factory = request.app.state.session_factory
    db = factory()
    try:
        yield db
    finally:
        db.close()
