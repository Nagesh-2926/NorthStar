"""
Debug email validation and backend database connection.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test 1: EmailStr validation
print("=" * 70)
print("TEST 1: EmailStr validation")
print("=" * 70)

from pydantic import BaseModel, EmailStr

class TestModel(BaseModel):
    email: EmailStr

# Test valid email
try:
    m = TestModel(email="coordinator@example.com")
    print(f"coordinator@example.com: VALID (normalized: {m.email})")
except Exception as e:
    print(f"coordinator@example.com: INVALID - {e}")

# Test invalid email
try:
    m2 = TestModel(email="demo.coordinator@demo.example.com")
    print(f"demo.coordinator@demo.example.com: VALID (normalized: {m2.email})")
except Exception as e:
    print(f"demo.coordinator@demo.example.com: INVALID - {e}")

# Test with uppercase
try:
    m3 = TestModel(email="Coordinator@Example.com")
    print(f"Coordinator@Example.com: VALID (normalized: {m3.email})")
except Exception as e:
    print(f"Coordinator@Example.com: INVALID - {e}")

# Test 2: Backend database connection
print("\n" + "=" * 70)
print("TEST 2: Backend database connection")
print("=" * 70)

from backend.app.core.config import Settings
from backend.app.db.session import build_engine, build_session_factory
from sqlalchemy import select, text
from backend.app.models.entities import User
from backend.app.core.security import verify_password

settings = Settings()
print(f"Database URL: {settings.database_url}")

engine = build_engine(settings.database_url)
Session = build_session_factory(engine)

with Session() as db:
    # Check if the user exists
    user = db.scalar(select(User).where(User.email == "coordinator@example.com"))
    if user:
        print(f"\nUser found: {user.email}")
        print(f"  Role: {user.role}")
        print(f"  Is active: {user.is_active}")
        print(f"  Token version: {user.token_version}")
        print(f"  Verify password: {verify_password('SecurePass1234', user.password_hash)}")
    else:
        print("\nUser NOT found!")
        
    # Check total user count
    count = db.scalar(text("SELECT COUNT(*) FROM users"))
    print(f"\nTotal users in database: {count}")
    
    # Check if there's a different database being used
    db_name = db.scalar(text("SELECT current_database()"))
    print(f"Current database: {db_name}")
