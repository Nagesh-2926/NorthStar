"""
Test login directly using the backend's own environment.
"""
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the backend modules directly
from backend.app.core.security import verify_password
from backend.app.core.config import Settings
from backend.app.db.session import build_engine, build_session_factory
from sqlalchemy import select
from backend.app.models.entities import User

# Load settings
settings = Settings()
print(f"Database URL: {settings.database_url}")
print(f"JWT Secret: {settings.jwt_secret_key.get_secret_value()[:20]}...")

# Connect to the database
engine = build_engine(settings.database_url)
Session = build_session_factory(engine)

with Session() as db:
    # Check the coordinator user
    user = db.scalar(select(User).where(User.email == "demo.coordinator@demo.example.com"))
    if user:
        print(f"\nUser found: {user.email}")
        print(f"  Role: {user.role}")
        print(f"  Is active: {user.is_active}")
        print(f"  Token version: {user.token_version}")
        print(f"  Password hash: {user.password_hash[:50]}...")
        print(f"  Verify 'SecurePass1234': {verify_password('SecurePass1234', user.password_hash)}")
    else:
        print("\nUser NOT found!")
        
    # Also check vinnukanna37@gmail.com
    user2 = db.scalar(select(User).where(User.email == "vinnukanna37@gmail.com"))
    if user2:
        print(f"\nUser found: {user2.email}")
        print(f"  Role: {user2.role}")
        print(f"  Is active: {user2.is_active}")
        print(f"  Token version: {user2.token_version}")
        print(f"  Verify 'SecurePass1234': {verify_password('SecurePass1234', user2.password_hash)}")
