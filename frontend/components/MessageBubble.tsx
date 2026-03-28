'use client'

import type { ChatMessage } from '@/lib/api'
import SourcesPanel from './SourcesPanel'
import FeedbackWidget from './FeedbackWidget'

interface Props {
  message: ChatMessage
  sessionId: string
  messageIndex: number
  isStreaming?: boolean
}

function SimpleMarkdown({ text }: { text: string }) {
  const lines = text.split('\n')
  return (
    <div className="space-y-1">
      {lines.map((line, i) => {
        if (line.startsWith('## ')) return <h3 key={i} className="font-semibold text-base mt-2">{line.slice(3)}</h3>
        if (line.startsWith('# ')) return <h2 key={i} className="font-bold text-lg mt-2">{line.slice(2)}</h2>
        if (line.startsWith('- ') || line.startsWith('* ')) {
          return (
            <div key={i} className="flex gap-2">
              <span className="text-gray-400 shrink-0">•</span>
              <span>{line.slice(2)}</span>
            </div>
          )
        }
        if (/^\d+\.\s/.test(line)) {
          const [num, ...rest] = line.split('. ')
          return (
            <div key={i} className="flex gap-2">
              <span className="text-gray-400 shrink-0 tabular-nums">{num}.</span>
              <span>{rest.join('. ')}</span>
            </div>
          )
        }
        if (line === '') return <div key={i} className="h-1" />
        // Inline bold: **text**
        const parts = line.split(/(\*\*[^*]+\*\*)/)
        return (
          <p key={i}>
            {parts.map((p, j) =>
              p.startsWith('**') && p.endsWith('**')
                ? <strong key={j}>{p.slice(2, -2)}</strong>
                : p
            )}
          </p>
        )
      })}
    </div>
  )
}

export default function MessageBubble({ message, sessionId, messageIndex, isStreaming }: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] px-4 py-2.5 rounded-2xl rounded-tr-sm
                        bg-blue-600 text-white text-sm leading-relaxed">
          {message.content}
          {message.timestamp && (
            <p className="mt-1 text-[10px] text-blue-200 text-right">{message.timestamp}</p>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] space-y-1">
        {/* Avatar */}
        <div className="flex items-end gap-2">
          <div className="w-6 h-6 rounded-full bg-blue-600 flex items-center justify-center shrink-0 mb-0.5">
            <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
          </div>
          <div className="px-4 py-3 rounded-2xl rounded-tl-sm
                          bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700
                          text-sm text-gray-800 dark:text-gray-200 leading-relaxed shadow-sm">
            {message.content
              ? <SimpleMarkdown text={message.content} />
              : isStreaming
                ? <span className="text-gray-400">Thinking…</span>
                : null
            }
            {isStreaming && <span className="streaming-cursor" aria-hidden />}

            {message.timestamp && (
              <p className="mt-1.5 text-[10px] text-gray-400">{message.timestamp}</p>
            )}
          </div>
        </div>

        {/* Sources */}
        {message.sources && message.sources.length > 0 && (
          <div className="ml-8">
            <SourcesPanel sources={message.sources} />
          </div>
        )}

        {/* Feedback — only after streaming completes */}
        {!isStreaming && message.content && sessionId && (
          <div className="ml-8">
            <FeedbackWidget sessionId={sessionId} messageIndex={messageIndex} />
          </div>
        )}
      </div>
    </div>
  )
}
