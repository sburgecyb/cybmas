import { getToken } from './api'

interface JWTPayload {
  sub: string
  role: string
  exp: number
}

function decodePayload(): JWTPayload | null {
  const token = getToken()
  if (!token) return null
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')))
    return payload as JWTPayload
  } catch {
    return null
  }
}

export function isAuthenticated(): boolean {
  const payload = decodePayload()
  if (!payload) return false
  return payload.exp * 1000 > Date.now()
}

export function getRole(): string | null {
  return decodePayload()?.role ?? null
}

export function getEngineerId(): string | null {
  return decodePayload()?.sub ?? null
}
