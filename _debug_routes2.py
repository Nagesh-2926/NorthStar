"""
Check if api_router is properly included.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app.main import create_app
from backend.app.core.config import Settings

app = create_app(Settings())

print("All routes (including mounted):")
for route in app.routes:
    print(f"  {type(route).__name__}: {getattr(route, 'path', 'N/A')} - {getattr(route, 'methods', 'N/A')}")

print(f"\nTotal routes: {len(app.routes)}")

# Check if api_router is in the app's router
print(f"\nApp router routes: {len(app.router.routes)}")
for route in app.router.routes:
    print(f"  {type(route).__name__}: {getattr(route, 'path', 'N/A')}")
