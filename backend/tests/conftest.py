"""Pytest configuration for ATOM backend tests."""
import os

# Use a fixed secret key in tests so JWT tokens are deterministic
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production")
# Point to a non-existent Redis so tests always use in-memory cache
os.environ.setdefault("REDIS_URL", "redis://localhost:19999/0")
