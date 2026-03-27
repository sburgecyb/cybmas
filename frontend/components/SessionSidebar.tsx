'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { getSessions, deleteSession } from '@/lib/api'
import type { SessionSummary } from '@/lib/api'

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1)   return 'Just now'
  if (mins < 60)  return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24)   return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days === 1) return 'Yesterday'
  return `${days} days ago`
}

export default function SessionSidebar() {
  const router = useRouter()
  const pathname = usePathname()
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  useEffect(() => {
    getSessions().then(s => { setSessions(s); setLoading(false) })
  }, [pathname])

  // Refresh when a new session is saved (fired by ChatWindow after done event)
  useEffect(() => {
    function onSessionSaved() {
      getSessions().then(s => setSessions(s))
    }
    window.addEventListener('cybmas:session-saved', onSessionSaved)
    return () => window.removeEventListener('cybmas:session-saved', onSessionSaved)
  }, [])

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation()
    await deleteSession(id)
    setSessions(prev => prev.filter(s => s.id !== id))
    if (pathname === `/chat/${id}`) router.push('/chat')
  }

  const activeId = pathname.startsWith('/chat/') ? pathname.split('/chat/')[1] : null

  return (
    <aside className="flex flex-col h-full bg-gray-50 dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800">
      {/* New chat */}
      <div className="p-3 border-b border-gray-200 dark:border-gray-800">
        <button
          onClick={() => router.push(`/chat?new=${Date.now()}`)}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg
                     bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Chat
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto py-2">
        {loading ? (
          <div className="px-3 space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="animate-pulse space-y-1.5">
                <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-4/5" />
                <div className="h-2.5 bg-gray-100 dark:bg-gray-800 rounded w-3/5" />
              </div>
            ))}
          </div>
        ) : sessions.length === 0 ? (
          <p className="px-4 py-8 text-xs text-center text-gray-400 dark:text-gray-500">
            No previous conversations
          </p>
        ) : (
          sessions.map(session => (
            <div
              key={session.id}
              onClick={() => router.push(`/chat/${session.id}`)}
              onMouseEnter={() => setHoveredId(session.id)}
              onMouseLeave={() => setHoveredId(null)}
              className={`relative group mx-2 px-3 py-2.5 rounded-lg cursor-pointer transition-colors
                ${activeId === session.id
                  ? 'bg-blue-100 dark:bg-blue-900/30'
                  : 'hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
            >
              <p className={`text-xs font-medium truncate pr-5 leading-tight
                ${activeId === session.id
                  ? 'text-blue-700 dark:text-blue-300'
                  : 'text-gray-700 dark:text-gray-300'
                }`}>
                {session.title ?? 'Untitled session'}
              </p>
              {session.last_message_preview && (
                <p className="text-[11px] text-gray-400 dark:text-gray-500 truncate mt-0.5 leading-tight">
                  {session.last_message_preview}
                </p>
              )}
              <p className="text-[10px] text-gray-400 dark:text-gray-600 mt-0.5">
                {relativeTime(session.updated_at)}
              </p>

              {/* Delete button */}
              {hoveredId === session.id && (
                <button
                  onClick={e => handleDelete(e, session.id)}
                  className="absolute right-2 top-2.5 p-0.5 rounded text-gray-400 hover:text-red-500
                             hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </aside>
  )
}
