'use client'

import { useEffect } from 'react'

const BUS = [
  { code: 'B1', label: 'Reservations Platform' },
  { code: 'B2', label: 'Payments Platform' },
]

const STORAGE_KEY = 'selected_bus'

interface Props {
  selected: string[]
  onChange: (bus: string[]) => void
}

export default function BusinessUnitSelector({ selected, onChange }: Props) {
  // Restore from sessionStorage on mount
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY)
      if (saved) {
        const parsed: string[] = JSON.parse(saved)
        if (Array.isArray(parsed) && parsed.length > 0) onChange(parsed)
      }
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function toggle(code: string) {
    let next: string[]
    if (selected.includes(code)) {
      if (selected.length === 1) return // must keep at least one
      next = selected.filter(b => b !== code)
    } else {
      next = [...selected, code]
    }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    onChange(next)
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs font-medium text-gray-500 dark:text-gray-400 shrink-0">Scope:</span>
      {BUS.map(bu => {
        const active = selected.includes(bu.code)
        return (
          <button
            key={bu.code}
            onClick={() => toggle(bu.code)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors border
              ${active
                ? 'bg-blue-600 text-white border-blue-600'
                : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:border-blue-400'
              }`}
          >
            {bu.code} — {bu.label}
          </button>
        )
      })}
    </div>
  )
}
