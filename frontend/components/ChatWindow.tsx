'use client'

import { useEffect, useRef, useState } from 'react'
import { chatStream, getSessionMessages } from '@/lib/api'
import type { ChatMessage, BusinessUnitScope, ChatMode } from '@/lib/api'
import MessageBubble from './MessageBubble'
import BusinessUnitSelector from './BusinessUnitSelector'
import IncidentToggle from './IncidentToggle'
import ChatModeSelector from './ChatModeSelector'

interface Props {
  initialSessionId?: string
  engineerId: string
}

export default function ChatWindow({ initialSessionId, engineerId }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputText, setInputText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId ?? null)
  const [selectedBUs, setSelectedBUs] = useState<string[]>(['B1', 'B2'])
  const [incidentsEnabled, setIncidentsEnabled] = useState(false)
  const [chatMode, setChatMode] = useState<ChatMode>('support_engineer')
  const [loadingHistory, setLoadingHistory] = useState(false)

  // Load existing session messages
  useEffect(() => {
    if (!initialSessionId) return
    setLoadingHistory(true)
    getSessionMessages(initialSessionId)
      .then(msgs => setMessages(msgs))
      .finally(() => setLoadingHistory(false))
  }, [initialSessionId])

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-resize textarea
  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInputText(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`
  }

  async function sendMessage() {
    const text = inputText.trim()
    if (!text || isStreaming) return

    setInputText('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'

    const userMsg: ChatMessage = { role: 'user', content: text, timestamp: new Date().toLocaleTimeString() }
    const assistantMsg: ChatMessage = { role: 'assistant', content: '' }

    setMessages(prev => [...prev, userMsg, assistantMsg])
    setIsStreaming(true)

    const scope: BusinessUnitScope = {
      business_units: selectedBUs,
      include_incidents: incidentsEnabled,
    }

    try {
      const stream = chatStream(text, sessionId, scope, chatMode)
      for await (const event of stream) {
        if (event.type === 'token' && event.content) {
          setMessages(prev => {
            const updated = [...prev]
            const last = { ...updated[updated.length - 1] }
            last.content = (last.content ?? '') + event.content
            updated[updated.length - 1] = last
            return updated
          })
        } else if (event.type === 'sources' && event.sources) {
          setMessages(prev => {
            const updated = [...prev]
            const last = { ...updated[updated.length - 1] }
            last.sources = event.sources
            updated[updated.length - 1] = last
            return updated
          })
        } else if (event.type === 'done') {
          if (event.session_id) {
            setSessionId(event.session_id)
            // Do NOT update the URL here — window.history.replaceState is
            // intercepted by Next.js App Router, which updates useSearchParams(),
            // changes the ChatWindow key, and remounts it (clearing all messages).
            // The session is saved to DB; the sidebar is notified via a custom event.
            if (typeof window !== 'undefined') {
              window.dispatchEvent(new CustomEvent('cybmas:session-saved'))
            }
          }
        } else if (event.type === 'error') {
          setMessages(prev => {
            const updated = [...prev]
            const last = { ...updated[updated.length - 1] }
            last.content = `⚠️ ${event.message ?? 'An error occurred'}`
            updated[updated.length - 1] = last
            return updated
          })
        }
      }
    } catch (err) {
      setMessages(prev => {
        const updated = [...prev]
        const last = { ...updated[updated.length - 1] }
        last.content = `⚠️ ${err instanceof Error ? err.message : 'Connection error'}`
        updated[updated.length - 1] = last
        return updated
      })
    } finally {
      setIsStreaming(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Context controls */}
      <div className="px-4 py-2.5 border-b border-gray-200 dark:border-gray-800
                      bg-white dark:bg-gray-900 flex flex-wrap items-center gap-4">
        <ChatModeSelector value={chatMode} onChange={setChatMode} />
        <div className="border-l border-gray-200 dark:border-gray-700 pl-4">
          <BusinessUnitSelector selected={selectedBUs} onChange={setSelectedBUs} />
        </div>
        <div className="border-l border-gray-200 dark:border-gray-700 pl-4">
          <IncidentToggle enabled={incidentsEnabled} onChange={setIncidentsEnabled} />
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-5">
        {loadingHistory ? (
          <div className="flex justify-center py-8">
            <svg className="animate-spin w-6 h-6 text-blue-500" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-gray-400 dark:text-gray-500 py-16">
            <div className="w-12 h-12 rounded-xl bg-blue-100 dark:bg-blue-900/20 flex items-center justify-center mb-4">
              <svg className="w-6 h-6 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
            </div>
            <p className="font-medium text-gray-600 dark:text-gray-400 text-sm mb-1">How can I help you?</p>
            <p className="text-xs max-w-xs">
              Ask about past tickets, incidents, or type a JIRA ID like <span className="font-mono bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded">B1-1008</span>
            </p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <MessageBubble
              key={i}
              message={msg}
              sessionId={sessionId ?? ''}
              messageIndex={i}
              isStreaming={isStreaming && i === messages.length - 1 && msg.role === 'assistant'}
            />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <div className="flex items-end gap-2 rounded-xl border border-gray-300 dark:border-gray-700
                        bg-white dark:bg-gray-800 px-3 py-2 focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-transparent transition">
          <textarea
            ref={textareaRef}
            rows={1}
            value={inputText}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            placeholder="Ask about a ticket, incident, or error…"
            className="flex-1 resize-none bg-transparent text-sm text-gray-900 dark:text-gray-100
                       placeholder-gray-400 dark:placeholder-gray-500
                       focus:outline-none disabled:opacity-50 leading-relaxed py-0.5"
          />
          <button
            onClick={sendMessage}
            disabled={isStreaming || !inputText.trim()}
            className="shrink-0 p-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-40
                       text-white transition-colors"
          >
            {isStreaming ? (
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            )}
          </button>
        </div>
        <p className="mt-1.5 text-[11px] text-gray-400 dark:text-gray-600 text-center">
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  )
}
