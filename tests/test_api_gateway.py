import asyncio
import sys
import os
sys.path.insert(0, '.')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'F:\cybmas\keys\cybmas-750d93f28bed.json'
os.environ['GCP_PROJECT_ID'] = 'cybmas'
os.environ['DATABASE_URL'] = 'postgresql+asyncpg://postgres:sa@127.0.0.1:5432/multi_agent'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:6379'
os.environ['JWT_SECRET_KEY'] = 'test-secret-key-minimum-32-chars-long-here'
os.environ['JWT_ALGORITHM'] = 'HS256'
os.environ['JWT_EXPIRY_HOURS'] = '8'
os.environ['CORS_ORIGINS'] = 'http://localhost:3000'
os.environ['ORCHESTRATOR_ENDPOINT'] = 'http://localhost:8001'

async def test():
    # Test 1 - Auth functions
    from services.api_gateway.auth import (
        hash_password, verify_password, create_token, decode_token
    )

    hashed = hash_password("TestPassword123")
    assert verify_password("TestPassword123", hashed)
    assert not verify_password("WrongPassword", hashed)
    print("OK - Password hashing and verification works")

    token = create_token("engineer@company.com", "engineer")
    payload = decode_token(token)
    assert payload['sub'] == "engineer@company.com"
    assert payload['role'] == "engineer"
    print(f"OK - JWT token created and decoded correctly")

    # Test 2 - FastAPI app starts
    from services.api_gateway.main import app
    print(f"OK - FastAPI app created: {app.title}")
    print(f"     Routes: {len(app.routes)}")

    # Test 3 - Routers registered
    route_paths = [r.path for r in app.routes if hasattr(r, 'path')]
    required = ['/health', '/api/auth/login', '/api/auth/register',
                '/api/auth/me', '/api/chat', '/api/sessions',
                '/api/feedback']
    for path in required:
        assert any(path in p for p in route_paths), f"Missing route: {path}"
    print(f"OK - All required routes registered")
    print(f"     Paths: {[p for p in route_paths if p.startswith('/api')]}")

    print("\nAll API Gateway tests passed")

asyncio.run(test())