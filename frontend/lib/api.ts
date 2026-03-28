const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Types ──────────────────────────────────────────────────────────────────────

export interface SearchResult {
  jira_id: string
  title: string
  summary?: string
  score: number
  result_type: 'ticket' | 'incident'
  status?: string
  business_unit?: string
}

export interface SSEEvent {
  type: 'token' | 'sources' | 'done' | 'error'
  content?: string
  sources?: SearchResult[]
  session_id?: string
  message?: string
}

export interface SessionSummary {
  id: string
  title?: string
  last_message_preview?: string
  updated_at: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
  sources?: SearchResult[]
}

export interface BusinessUnitScope {
  business_units: string[]
  include_incidents: boolean
}

/** Workspace mode; only support_engineer runs the full support stack today. */
export type ChatMode =
  | 'support_engineer'
  | 'query_analyst'
  | 'requirements'
  | 'qa'

// ── Token helpers ──────────────────────────────────────────────────────────────

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('access_token')
}

export function setToken(token: string): void {
  localStorage.setItem('access_token', token)
}

export function clearToken(): void {
  localStorage.removeItem('access_token')
}

// ── Base request ───────────────────────────────────────────────────────────────

async function apiRequest(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_URL}${path}`, { ...options, headers })

  if (res.status === 401) {
    clearToken()
    if (typeof window !== 'undefined') window.location.href = '/login'
    throw new Error('Session expired. Redirecting to login.')
  }

  return res
}

// ── Auth ───────────────────────────────────────────────────────────────────────

export async function login(
  email: string,
  password: string,
): Promise<{ access_token: string; engineer_id: string; role: string }> {
  const res = await fetch(`${API_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Login failed')
  }
  return res.json()
}

export async function logout(): Promise<void> {
  await apiRequest('/api/auth/logout', { method: 'POST' }).catch(() => {})
  clearToken()
}

export async function getMe(): Promise<{
  engineer_id: string
  full_name: string
  role: string
}> {
  const res = await apiRequest('/api/auth/me')
  if (!res.ok) throw new Error('Failed to fetch user info')
  return res.json()
}

// ── Chat (SSE streaming) ───────────────────────────────────────────────────────

export async function* chatStream(
  message: string,
  sessionId: string | null,
  contextScope: BusinessUnitScope,
  chatMode: ChatMode = 'support_engineer',
): AsyncGenerator<SSEEvent> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_URL}/api/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      message,
      session_id: sessionId,
      context_scope: contextScope,
      chat_mode: chatMode,
    }),
  })

  if (!res.ok || !res.body) {
    if (res.status === 401) {
      clearToken()
      if (typeof window !== 'undefined') window.location.href = '/login'
    }
    yield { type: 'error', message: `HTTP ${res.status}` }
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const raw = line.slice(6).trim()
        if (!raw || raw === '[DONE]') continue
        try {
          yield JSON.parse(raw) as SSEEvent
        } catch {
          // skip malformed line
        }
      }
    }
  }
}

// ── Sessions ───────────────────────────────────────────────────────────────────

export async function getSessions(): Promise<SessionSummary[]> {
  const res = await apiRequest('/api/sessions')
  if (!res.ok) return []
  const data = await res.json()
  return data.sessions ?? []
}

export async function getSessionMessages(
  sessionId: string,
): Promise<ChatMessage[]> {
  const res = await apiRequest(`/api/chat/${sessionId}/messages`)
  if (!res.ok) return []
  const data = await res.json()
  return data.messages ?? []
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiRequest(`/api/sessions/${sessionId}`, { method: 'DELETE' })
}

// ── Feedback ───────────────────────────────────────────────────────────────────

export async function submitFeedback(
  sessionId: string,
  messageIndex: number,
  rating: 'correct' | 'can_be_better' | 'incorrect',
  comment?: string,
): Promise<void> {
  await apiRequest('/api/feedback', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, message_index: messageIndex, rating, comment }),
  })
}
