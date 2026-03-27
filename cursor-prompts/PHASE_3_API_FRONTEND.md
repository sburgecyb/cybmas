# Cursor Build Prompts — Phase 3: API Gateway & Frontend

---
#prompt 3.1 API Gateway Service by Claude
Refer to .cursorrules for all conventions. Create the complete API Gateway 
service at services/api_gateway/

Create these files:

1. services/api_gateway/__init__.py (empty)

2. services/api_gateway/auth.py

Imports:
- os, sys, json
- from datetime import datetime, timezone, timedelta
- from jose import jwt, JWTError
- from passlib.context import CryptContext
- asyncpg
- structlog
- sys.path.insert(0, '.')

Module-level:
- pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
- JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
- JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
- JWT_EXPIRY_HOURS = int(os.getenv('JWT_EXPIRY_HOURS', '8'))

Functions:

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_token(email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)
    payload = {"sub": email, "role": role, "exp": expire}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

async def get_user_by_email(pool: asyncpg.Pool, email: str) -> dict | None:
    row = await pool.fetchrow(
        "SELECT id, email, hashed_password, full_name, role, is_active FROM users WHERE email = $1",
        email.lower()
    )
    return dict(row) if row else None

async def create_user(pool: asyncpg.Pool, email: str, 
                      hashed_password: str, full_name: str = None) -> dict:
    row = await pool.fetchrow(
        """INSERT INTO users (email, hashed_password, full_name, role)
           VALUES ($1, $2, $3, 'engineer')
           RETURNING id, email, full_name, role""",
        email.lower(), hashed_password, full_name
    )
    return dict(row)

async def update_last_login(pool: asyncpg.Pool, email: str) -> None:
    await pool.execute(
        "UPDATE users SET last_login = NOW() WHERE email = $1",
        email.lower()
    )


3. services/api_gateway/middleware/__init__.py (empty)

4. services/api_gateway/middleware/auth_middleware.py

Imports:
- fastapi Request, HTTPException, status
- fastapi.security HTTPBearer, HTTPAuthorizationCredentials
- from jose import JWTError
- from services.api_gateway.auth import decode_token
- structlog

security = HTTPBearer(auto_error=False)

async def get_current_engineer(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    - Skip auth if path is /health or starts with /api/auth
    - If no credentials: raise HTTPException 401 "Not authenticated"
    - Try decode_token(credentials.credentials)
    - Extract sub (email) and role from payload
    - Attach to request.state: engineer_id, role
    - Return {"engineer_id": email, "role": role}
    - On JWTError: raise HTTPException 401 "Invalid or expired token"
    - Never log the token itself


5. services/api_gateway/middleware/rate_limit.py

Imports:
- fastapi Request, HTTPException
- redis.asyncio as redis
- time, os
- structlog

async def check_rate_limit(request: Request) -> None:
    - Get engineer_id from request.state (set by auth middleware)
    - If no engineer_id: return (skip rate limiting for unauthenticated)
    - Redis key: f"ratelimit:{engineer_id}:{int(time.time() // 60)}"
    - INCR the key, set TTL to 120 seconds on first call
    - If count > 60: raise HTTPException 429 with 
      Retry-After header = seconds until next minute
    - Use REDIS_URL from env


6. services/api_gateway/routers/__init__.py (empty)

7. services/api_gateway/routers/auth_router.py

Imports:
- fastapi APIRouter, HTTPException, Depends, status
- from services.api_gateway.auth import (
    verify_password, hash_password, create_token,
    get_user_by_email, create_user, update_last_login)
- from services.shared.models import UserLogin, UserCreate, TokenResponse
- asyncpg
- structlog

router = APIRouter(prefix="/api/auth", tags=["auth"])

POST /api/auth/login
- Input: UserLogin
- Get user by email from DB
- If not found or password wrong: raise 401 
  "Invalid email or password" (same message for both — no enumeration)
- If user inactive: raise 401 "Account disabled"
- Create JWT token
- Update last_login
- Return TokenResponse

POST /api/auth/register  
- Input: UserCreate
- Check if email already exists
- If exists: raise 409 "Email already registered"
- Hash password, create user
- Return 200 {"engineer_id": email, "message": "Account created"}

GET /api/auth/me
- Auth required (Depends on get_current_engineer)
- Return {"engineer_id", "full_name", "role"} from DB

POST /api/auth/logout
- Auth required
- Return 200 {"message": "Logged out"}

Dependency to get DB pool:
async def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool


8. services/api_gateway/routers/chat_router.py

Imports:
- fastapi APIRouter, Depends, Request, HTTPException
- fastapi.responses StreamingResponse
- httpx
- json, asyncio, uuid, os
- structlog
- from services.api_gateway.middleware.auth_middleware import get_current_engineer
- from services.shared.models import BusinessUnitScope, AgentRequest, ChatMessage

router = APIRouter(prefix="/api/chat", tags=["chat"])

POST /api/chat
- Auth required
- Input body: { message: str, session_id: str | None, 
                context_scope: BusinessUnitScope }
- If no session_id: generate new uuid
- Build AgentRequest
- Forward to ORCHESTRATOR_ENDPOINT/process as POST
- Stream response back as SSE (text/event-stream)
- SSE events format:
    data: {"type": "token", "content": "..."}
    data: {"type": "done", "session_id": "..."}
    data: {"type": "error", "message": "..."}
- If orchestrator unreachable: return SSE error event

GET /api/chat/{session_id}/messages
- Auth required
- Query chat_sessions WHERE id = session_id 
  AND engineer_id = current engineer (403 if mismatch)
- Return messages list


9. services/api_gateway/routers/sessions_router.py

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

GET /api/sessions
- Auth required
- Query chat_sessions WHERE engineer_id = current_engineer
  ORDER BY updated_at DESC LIMIT 20
- Return list of session summaries:
  {id, title, last_message_preview (first 100 chars of last message), updated_at}
- Parse JSONB messages field (handle both str and list)

DELETE /api/sessions/{session_id}
- Auth required
- Verify ownership (403 if not owner)
- Delete from chat_sessions


10. services/api_gateway/routers/feedback_router.py

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

POST /api/feedback
- Auth required
- Input: {session_id, message_index, rating, comment?}
- Verify session belongs to engineer (403 if not)
- Insert into engineer_feedback table
- Return 200 {"saved": True}

GET /api/feedback/summary
- Auth required, admin role only
- If role != "admin": raise 403
- Query engineer_feedback with date range (last 7 days default)
- Return {total, correct, can_be_better, incorrect, accuracy_pct}


11. services/api_gateway/main.py

Imports:
- fastapi FastAPI, Request, Depends
- fastapi.middleware.cors CORSMiddleware
- contextlib asynccontextmanager
- asyncpg
- redis.asyncio as redis
- structlog
- dotenv load_dotenv
- os, sys
- sys.path.insert(0, '.')
- All routers

load_dotenv('.env.local')

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.db_pool = await asyncpg.create_pool(
        os.getenv('DATABASE_URL').replace('postgresql+asyncpg://', 'postgresql://'),
        min_size=2, max_size=10
    )
    app.state.redis = redis.from_url(os.getenv('REDIS_URL'))
    logger.info("api_gateway.started")
    yield
    # Shutdown
    await app.state.db_pool.close()
    await app.state.redis.aclose()

app = FastAPI(title="Multi-Agent Platform API", lifespan=lifespan)

CORS:
- Allow origins from CORS_ORIGINS env var (comma separated)
- Allow methods: GET, POST, PUT, DELETE, OPTIONS
- Allow headers: *
- Allow credentials: True

Include routers:
- auth_router
- chat_router  
- sessions_router
- feedback_router

GET /health (no auth):
- Return {"status": "ok", "service": "api-gateway"}

Global exception handler:
- Catch all unhandled exceptions
- Log with structlog
- Return {"detail": "Internal server error"} with 500

requirements.txt for services/api_gateway/:
fastapi==0.111.0
uvicorn==0.30.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
asyncpg==0.29.0
redis==5.0.4
httpx==0.27.0
structlog==24.1.0
python-dotenv==1.0.1
pydantic>=2.0
---

## PROMPT 3.1 — API Gateway Service

```
Create the API Gateway service at services/api-gateway/.

1. services/api-gateway/main.py
   - FastAPI app with CORS configured for frontend domain (CORS_ORIGINS env var)
   - Mount routers: /api/auth, /api/chat, /api/sessions, /api/feedback
   - Global exception handler returning structured error JSON
   - Health check: GET /health (no auth)
   - Startup: initialise DB pool and Redis pool

2. services/api-gateway/middleware/auth.py
   - JWT token validation using python-jose
   - JWT_SECRET_KEY and JWT_ALGORITHM from env vars
   - Extract engineer_id (email) and role from token payload
   - Attach to request.state: engineer_id, role
   - Skip auth on /health and /api/auth/* routes
   - Return 401 with clear message on invalid/expired token

3. services/api-gateway/routers/auth.py

POST /api/auth/login
- Input: { email: str, password: str }
- Fetch user from users table by email
- Verify password with passlib bcrypt: verify(password, hashed_password)
- If valid: create JWT with payload { sub: email, role: role, exp: now + JWT_EXPIRY_HOURS }
- Update last_login timestamp
- Return: { access_token: str, token_type: "bearer", engineer_id: email, role: role }
- Return 401 if credentials invalid (same message for both wrong email and wrong password)

POST /api/auth/register
- Input: { email: str, password: str, full_name: str }
- Validate: password min 8 chars
- Hash password with passlib bcrypt
- Insert into users table
- Return: { engineer_id: email, message: "Account created" }
- Return 409 if email already exists

POST /api/auth/logout
- Auth required
- Client-side only (JWT is stateless) — return 200 OK
- Optionally: add token to a Redis blocklist (key: blocklist:{jti}, TTL = remaining expiry)

GET /api/auth/me
- Auth required
- Returns: { engineer_id, full_name, role }

4. services/api-gateway/middleware/rate_limit.py
   - Per-engineer rate limit: 60 requests per minute
   - Store counters in Redis: key = ratelimit:{engineer_id}:{minute_window}
   - Return 429 with Retry-After header if exceeded

5. services/api-gateway/routers/chat.py

POST /api/chat
- Auth required
- Input: { message: str, session_id: str | null, context_scope: BusinessUnitScope }
- If no session_id: create new session via session-agent
- Forward to orchestrator with AgentRequest
- Return StreamingResponse (text/event-stream)
- SSE format:
  data: {"type": "token", "content": "..."}
  data: {"type": "sources", "sources": [...]}
  data: {"type": "done", "session_id": "..."}

GET /api/chat/{session_id}/messages
- Auth required
- Returns full session messages
- Verify engineer_id matches session owner (403 if not)

6. services/api-gateway/routers/sessions.py

GET /api/sessions
- Auth required
- Returns list of engineer's own sessions (from session-agent)
- Ordered by updated_at DESC, limit 20

DELETE /api/sessions/{session_id}
- Auth required
- Soft delete (set deleted_at) — only own sessions

7. services/api-gateway/routers/feedback.py

POST /api/feedback
- Auth required
- Input: { session_id, message_index, rating, comment? }
- Forwards to session-agent save_feedback
- Returns 200 OK

GET /api/feedback/summary
- Auth required, admin role only (check request.state.role == 'admin')
- Returns feedback summary stats

8. services/api-gateway/repositories/user_repository.py
   - get_user_by_email(pool, email) -> User | None
   - create_user(pool, email, hashed_password, full_name) -> User
   - update_last_login(pool, email) -> None
   - All async using asyncpg

9. Dockerfile + requirements.txt
   - python-jose[cryptography], passlib[bcrypt], fastapi, uvicorn
   - asyncpg, redis, httpx, structlog, pydantic>=2.0
```

---

## PROMPT 3.2 — Frontend: Chat Interface

```
Create the Next.js 14 frontend for the support agent chat interface.

Use Next.js 14 App Router, TypeScript, Tailwind CSS.

1. frontend/lib/api.ts
   - Typed API client
   - All functions read JWT token from localStorage key 'access_token'
   - Attach as Authorization: Bearer <token> header on every request
   - If 401 received: clear token from localStorage and redirect to /login

   Functions:
   - login(email, password): Promise<{ access_token, engineer_id, role }>
   - logout(): void — clears localStorage
   - getMe(): Promise<{ engineer_id, full_name, role }>
   - chatStream(message, sessionId, contextScope): AsyncGenerator<SSEEvent>
     - Uses fetch + ReadableStream to consume SSE
     - Yields { type: 'token'|'sources'|'done', content?, sources?, session_id? }
   - getSessions(): Promise<SessionSummary[]>
   - getSessionMessages(sessionId): Promise<ChatMessage[]>
   - submitFeedback(sessionId, messageIndex, rating, comment?): Promise<void>

2. frontend/components/ChatWindow.tsx
   - Main chat interface
   - Props: initialSessionId?, engineerId
   - State: messages, isStreaming, currentSession
   - Renders: message list + input bar
   - On send: calls chatStream, appends tokens to last assistant message in real-time
   - Shows sources panel when sources SSE event received
   - Auto-scrolls to bottom on new tokens

3. frontend/components/MessageBubble.tsx
   - Renders user and assistant messages
   - User: right-aligned, blue bubble
   - Assistant: left-aligned, neutral card
   - Assistant messages include: response text (markdown rendered), sources (collapsible), feedback widget
   - Streaming state: show blinking cursor on last token

4. frontend/components/FeedbackWidget.tsx
   - Three buttons: ✓ Correct | ~ Can be better | ✗ Incorrect
   - On click: highlight selected, show optional comment textarea, submit on blur or enter
   - Disable after submission, show "Thank you" state
   - Calls submitFeedback API

5. frontend/components/BusinessUnitSelector.tsx
   - Multi-select dropdown: B1, B2 (fetched from GET /api/business-units)
   - Selected BUs shown as pills
   - At least one BU must be selected
   - Persisted to sessionStorage

6. frontend/components/IncidentToggle.tsx
   - Toggle switch: "Include Incident Management KB"
   - Show for all users in MVP (role-based restriction can be added later)
   - State change triggers context_scope update

7. frontend/components/SessionSidebar.tsx
   - Left sidebar listing past sessions
   - Session item: title (first message truncated), relative timestamp
   - Click: navigate to /chat/[sessionId]
   - "New Chat" button at top

8. frontend/app/chat/page.tsx
   - Default new chat page
   - Renders: SessionSidebar + BusinessUnitSelector + IncidentToggle + ChatWindow

9. frontend/app/chat/[sessionId]/page.tsx
   - Load existing session via getSessionMessages
   - Pre-populate ChatWindow with history

Design requirements:
- Clean, professional dark/light mode support (system preference)
- Tailwind only — no external component libraries
- Mobile responsive
- Accessible: proper aria labels on all interactive elements
```

---

## PROMPT 3.3 — Frontend: Auth & Session State

```
Add JWT authentication to the frontend. No Firebase or external auth service.

1. frontend/lib/auth.ts
   - TOKEN_KEY = 'access_token' (localStorage key)
   - getToken(): string | null — reads from localStorage
   - setToken(token: string): void — writes to localStorage
   - clearToken(): void — removes from localStorage
   - isAuthenticated(): boolean — checks token exists and is not expired
     (decode JWT payload without verifying signature, check exp field)
   - getRole(): string | null — decode role from token payload

2. frontend/hooks/useAuth.ts
   - State: { engineer_id, role, isAuthenticated, isLoading }
   - On mount: check localStorage for token, validate expiry, fetch /api/auth/me
   - login(email, password): calls api.login(), stores token, updates state
   - logout(): calls api.logout(), clears token, redirects to /login

3. frontend/components/AuthGuard.tsx
   - Wraps all protected routes
   - On mount: checks isAuthenticated()
   - If not authenticated: redirect to /login immediately
   - Shows loading spinner while checking

4. frontend/app/login/page.tsx
   - Clean login form: email input + password input + "Sign In" button
   - Show/hide password toggle
   - Error message display on failed login (e.g. "Invalid email or password")
   - Loading state on submit button while request in flight
   - On success: store token, redirect to /chat
   - No registration form on login page (engineers are added by admin)
   - Tailwind styling, no external UI library

5. frontend/app/layout.tsx
   - Wrap entire app in AuthGuard except /login route

6. frontend/hooks/useChat.ts
   - Manages chat state: messages, isStreaming, currentSessionId
   - sendMessage(text: string): starts SSE stream, appends tokens in real-time
   - loadSession(sessionId: string): fetches and sets historical messages
   - contextScope: { business_units, include_incidents } — derived from selector/toggle state
   - Handles 401 response: calls logout() automatically

7. frontend/hooks/useSession.ts
   - sessions: SessionSummary[] state
   - fetchSessions(): calls getSessions() API, updates state
   - deleteSession(sessionId): calls DELETE API, removes from local state
   - Persists active session_id to sessionStorage
```

---

## PROMPT 3.4 — Source Citations Component

```
Create the source citations panel shown after each assistant response.

frontend/components/SourcesPanel.tsx

Props: sources: SearchResult[], isVisible: boolean

Renders a collapsible panel below the assistant message showing retrieved sources.

Each source card:
- JIRA ID as a badge (B1-1234 style), clickable — opens JIRA URL in new tab
- Result type badge: "Ticket" or "Incident" (different color)
- Summary text (truncated to 120 chars)
- Relevance score as a small pill (e.g. 94% match)
- Status badge (Open / Resolved / In Progress)

Panel header:
- "{N} sources found" with expand/collapse chevron
- Collapsed by default, opens on click

Styling:
- Subtle border, smaller font than main response
- Incident sources use amber accent, ticket sources use blue accent
- Empty state: "No sources retrieved" in muted text
```
