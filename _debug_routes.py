"""
Check the app's route table.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app.main import create_app
from backend.app.core.config import Settings

app = create_app(Settings())

print("Routes:")
for route in app.routes:
    if hasattr(route, 'methods'):
        print(f"  {route.methods} {route.path}")
    elif hasattr(route, 'path'):
        print(f"  {route.path}")
