import asyncio
import uuid
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.models.user import User, UserRole

# Override dependencies
from app.dependencies.auth import get_current_user, require_role

def override_require_role(*roles):
    async def _mock_admin():
        user = User(id=uuid.uuid4(), username="admin", email="admin@example.com", role=UserRole.ADMIN, is_active=True)
        return user
    return _mock_admin

app.dependency_overrides[require_role(UserRole.ADMIN)] = override_require_role(UserRole.ADMIN)

client = TestClient(app)

print("Testing /admin/usage/summary...")
r = client.get("/api/v1/admin/usage/summary")
print(r.status_code, r.text)

print("Testing /admin/usage/by-provider...")
r = client.get("/api/v1/admin/usage/by-provider")
print(r.status_code, r.text)

print("Testing /admin/usage/by-stage...")
r = client.get("/api/v1/admin/usage/by-stage")
print(r.status_code, r.text)

print("Testing /admin/usage/by-run...")
r = client.get("/api/v1/admin/usage/by-run")
print(r.status_code, r.text)

print("Testing /admin/usage/calls...")
r = client.get("/api/v1/admin/usage/calls")
print(r.status_code, r.text)
