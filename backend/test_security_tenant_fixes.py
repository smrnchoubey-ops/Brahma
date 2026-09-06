import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.models.user import User
from app.models.task import Task
from app.models.audit import Audit
from app.core.security import get_password_hash, create_access_token
from main import app

# Create in-memory SQLite DB for testing
TEST_DB_URL = "sqlite:///./test_tenant_security.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

Base.metadata.create_all(bind=test_engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

def setup_data():
    db = TestingSessionLocal()
    db.query(Audit).delete()
    db.query(Task).delete()
    db.query(User).delete()
    db.commit()

    # User 1 (Tenant 1)
    user1 = User(username="tenant1", hashed_password=get_password_hash("pass123"))
    # User 2 (Tenant 2)
    user2 = User(username="tenant2", hashed_password=get_password_hash("pass123"))
    db.add(user1)
    db.add(user2)
    db.commit()
    db.refresh(user1)
    db.refresh(user2)

    u1_id = user1.id
    u2_id = user2.id

    # Task for User 1
    t1 = Task(user_id=u1_id, title="User1 Task", prompt="Task 1 prompt", status="COMPLETED")
    # Task for User 2
    t2 = Task(user_id=u2_id, title="User2 Task", prompt="Task 2 prompt", status="FAILED")
    db.add(t1)
    db.add(t2)
    db.commit()
    db.refresh(t1)
    db.refresh(t2)

    # Audit log for User 1's task
    a1 = Audit(task_id=t1.id, agent="KARMA", event_type="TASK_CREATED", status="SUCCESS", payload_snapshot={"msg": "User1 secret data"})
    # Audit log for User 2's task
    a2 = Audit(task_id=t2.id, agent="KARMA", event_type="TASK_FAILED", status="FAILED", payload_snapshot={"msg": "User2 secret data"})
    db.add(a1)
    db.add(a2)
    db.commit()
    db.close()
    return u1_id, u2_id

def test_health_check():
    print("Testing /health active DB probe...")
    response = client.get("/health")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    print("  [PASS] /health returned 200 with active DB check:", data)

def test_upload_unauthenticated_blocked():
    print("Testing /upload/ requires authentication...")
    response = client.post("/upload/", files={"file": ("test.txt", b"sample content", "text/plain")})
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    print("  [PASS] /upload/ correctly rejected unauthenticated request with 401")

def test_tenant_isolation_metrics():
    u1_id, u2_id = setup_data()
    token1 = create_access_token({"sub": "tenant1"})
    token2 = create_access_token({"sub": "tenant2"})

    print("Testing /api/metrics tenant isolation...")
    # User 1 metrics
    res1 = client.get("/api/metrics", headers={"Authorization": f"Bearer {token1}"})
    assert res1.status_code == 200
    m1 = res1.json()
    assert m1["total"] == 1, f"Expected User 1 total=1, got {m1['total']}"
    assert m1["completed"] == 1
    assert m1["failed"] == 0
    print("  [PASS] User 1 metrics scoped correctly (total=1, completed=1, failed=0):", m1)

    # User 2 metrics
    res2 = client.get("/api/metrics", headers={"Authorization": f"Bearer {token2}"})
    assert res2.status_code == 200
    m2 = res2.json()
    assert m2["total"] == 1, f"Expected User 2 total=1, got {m2['total']}"
    assert m2["completed"] == 0
    assert m2["failed"] == 1
    print("  [PASS] User 2 metrics scoped correctly (total=1, completed=0, failed=1):", m2)

def test_tenant_isolation_audit():
    u1_id, u2_id = setup_data()
    token1 = create_access_token({"sub": "tenant1"})
    token2 = create_access_token({"sub": "tenant2"})

    print("Testing /api/audit tenant isolation...")
    # User 1 audit
    res1 = client.get("/api/audit", headers={"Authorization": f"Bearer {token1}"})
    assert res1.status_code == 200
    events1 = res1.json()
    assert len(events1) == 1
    assert events1[0]["payload_snapshot"]["msg"] == "User1 secret data"
    print("  [PASS] User 1 only received User 1's audit event")

    # User 2 audit
    res2 = client.get("/api/audit", headers={"Authorization": f"Bearer {token2}"})
    assert res2.status_code == 200
    events2 = res2.json()
    assert len(events2) == 1
    assert events2[0]["payload_snapshot"]["msg"] == "User2 secret data"
    print("  [PASS] User 2 only received User 2's audit event")

def test_cors_headers():
    print("Testing CORS response headers...")
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET"
        }
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    print("  [PASS] CORS allowed configured origin 'http://localhost:3000'")

if __name__ == "__main__":
    test_health_check()
    test_upload_unauthenticated_blocked()
    test_tenant_isolation_metrics()
    test_tenant_isolation_audit()
    test_cors_headers()
    print("\n==========================================")
    print("ALL 5 VERIFICATION SUITES PASSED CLEANLY!")
    print("==========================================")
