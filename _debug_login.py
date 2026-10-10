"""
Debug the login endpoint directly to find the root cause.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app.core.config import Settings
from backend.app.db.session import build_engine, build_session_factory
from backend.app.core.security import verify_password
from sqlalchemy import select
from backend.app.models.entities import User
from backend.app.api.routes.auth import login
from backend.app.schemas.common import LoginRequest
from fastapi import HTTPException

# Load settings
settings = Settings()
print(f"Database URL: {settings.database_url}")

# Connect to the database
engine = build_engine(settings.database_url)
Session = build_session_factory(engine)

with Session() as db:
    # Check the coordinator user
    user = db.scalar(select(User).where(User.email == "coordinator@example.com"))
    if user:
        print(f"\nUser found: {user.email}")
        print(f"  Role: {user.role}")
        print(f"  Is active: {user.is_active}")
        print(f"  Token version: {user.token_version}")
        print(f"  Password hash: {user.password_hash[:50]}...")
        print(f"  Verify 'SecurePass1234': {verify_password('SecurePass1234', user.password_hash)}")
        
        # Try to call the login function directly
        print("\nTrying to call login function directly...")
        try:
            # Create a mock request object
            class MockRequest:
                class state:
                    settings = settings
            
            body = LoginRequest(email="coordinator@example.com", password="SecurePass1234")
            print(f"  LoginRequest email: {body.email}")
            print(f"  LoginRequest password: {body.password}")
            
            result = login(body, MockRequest(), db)
            print(f"  Result: {result}")
        except HTTPException as e:
            print(f"  HTTPException: {e.status_code} - {e.detail}")
        except Exception as e:
            print(f"  Exception: {type(e).__name__}: {e}")
    else:
        print("\nUser NOT found!")
        
    # Also check the demo coordinator
    user2 = db.scalar(select(User).where(User.email == "demo.coordinator@demo.example.com"))
    if user2:
        print(f"\nDemo coordinator found: {user2.email}")
        print(f"  Verify 'SecurePass1234': {verify_password('SecurePass1234', user2.password_hash)}")
