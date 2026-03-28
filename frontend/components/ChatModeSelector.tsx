'use client'

import { useEffect } from 'react'
import type { ChatMode } from '@/lib/api'

const OPTIONS: { value: ChatMode; label: string }[] = [
  { value: 'support_engineer', label: 'Support Engineer' },
  { value: 'query_analyst', label: 'Query Analyst' },
  { value: 'requirements', label: 'Requirements' },
  { value: 'qa', label: 'QA' },
]

const STORAGE_KEY = 'chat_mode'

interface Props {
  value: ChatMode
  onChange: (mode: ChatMode) => void
}

export default function ChatModeSelector({ value, onChange }: Props) {
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY)
      if (saved && OPTIONS.some(o => o.value === saved)) {
        onChange(saved as ChatMode)
      }
    } catch {
      /* ignore */
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const next = e.target.value as ChatMode
    try {
      sessionStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* ignore */
    }
    onChange(next)
  }

  return (
    <div className="flex items-center gap-2">
      <label
        htmlFor="chat-mode"
        className="text-xs font-medium text-gray-500 dark:text-gray-400 shrink-0"
      >
        Mode:
      </label>
      <select
        id="chat-mode"
        value={value}
        onChange={handleChange}
        className="text-xs rounded-lg border border-gray-300 dark:border-gray-600
                   bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                   px-2.5 py-1.5 min-w-[10.5rem] cursor-pointer
                   focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
      >
        {OPTIONS.map(o => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}
