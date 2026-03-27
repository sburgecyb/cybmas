'use client'

import { useEffect } from 'react'

const STORAGE_KEY = 'incidents_enabled'

interface Props {
  enabled: boolean
  onChange: (v: boolean) => void
}

export default function IncidentToggle({ enabled, onChange }: Props) {
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY)
      if (saved !== null) onChange(saved === 'true')
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function toggle() {
    const next = !enabled
    sessionStorage.setItem(STORAGE_KEY, String(next))
    onChange(next)
  }

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={toggle}
        className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent
          transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
          ${enabled ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'}`}
        role="switch"
        aria-checked={enabled}
      >
        <span
          className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow
            transition duration-200 ${enabled ? 'translate-x-4' : 'translate-x-0'}`}
        />
      </button>
      <div>
        <p className="text-xs font-medium text-gray-700 dark:text-gray-300 leading-tight">
          Include Incident Management KB
        </p>
        <p className="text-xs text-gray-400 dark:text-gray-500 leading-tight">Search past incidents and RCAs</p>
      </div>
    </div>
  )
}
