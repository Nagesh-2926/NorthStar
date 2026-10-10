"""
Debug the verify_password function directly.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app.core.config import Settings
from backend.app.db.session import build_engine, build_session_factory
from sqlalchemy import select
from backend.app.models.entities import User
from backend.app.core.security import verify_password, hash_password

# Load settings
settings = Settings()

# Connect to the database
engine = build_engine(settings.database_url)
Session = build_session_factory(engine)

with Session() as db:
    # Get the user
    user = db.scalar(select(User).where(User.email == "coordinator@example.com"))
    if user:
        print(f"User: {user.email}")
        print(f"Stored hash: {user.password_hash}")
        
        # Test verify_password with different passwords
        for pw in ["SecurePass1234", "securepass1234", "securepass1234", "password", "demo1234"]:
            result = verify_password(pw, user.password_hash)
            print(f"  verify_password('{pw}'): {result}")
        
        # Create a new hash and verify it
        new_hash = hash_password("SecurePass1234")
        print(f"\nNew hash: {new_hash}")
        print(f"verify_password('SecurePass1234', new_hash): {verify_password('SecurePass1234', new_hash)}")
        
        # Check if the stored hash is valid argon2
        print(f"\nHash algorithm: {user.password_hash.split('$')[1]}")
        print(f"Hash params: {user.password_hash.split('$')[3]}")
