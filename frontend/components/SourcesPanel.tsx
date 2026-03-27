'use client'

import { useState } from 'react'
import type { SearchResult } from '@/lib/api'

interface Props {
  sources: SearchResult[]
  isVisible: boolean
}

export default function SourcesPanel({ sources, isVisible }: Props) {
  const [open, setOpen] = useState(false)

  if (!isVisible || sources.length === 0) return null

  return (
    <div className="mt-3 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2
                   bg-gray-50 dark:bg-gray-800/60 hover:bg-gray-100 dark:hover:bg-gray-800
                   text-xs font-medium text-gray-600 dark:text-gray-400 transition-colors"
      >
        <span>{sources.length} source{sources.length !== 1 ? 's' : ''} found</span>
        <svg
          className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Source cards */}
      {open && (
        <div className="divide-y divide-gray-100 dark:divide-gray-800">
          {sources.map((src, i) => {
            const isIncident = src.result_type === 'incident'
            return (
              <div key={i} className="px-3 py-2.5 text-xs space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  {/* JIRA ID badge */}
                  <span className={`px-1.5 py-0.5 rounded font-mono font-semibold
                    ${isIncident
                      ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
                      : 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400'
                    }`}>
                    {src.jira_id}
                  </span>
                  {/* Type */}
                  <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide font-medium
                    ${isIncident
                      ? 'bg-amber-50 dark:bg-amber-950/20 text-amber-600 dark:text-amber-500'
                      : 'bg-blue-50 dark:bg-blue-950/20 text-blue-600 dark:text-blue-500'
                    }`}>
                    {src.result_type}
                  </span>
                  {/* Status */}
                  {src.status && (
                    <span className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700/50 text-gray-600 dark:text-gray-400">
                      {src.status}
                    </span>
                  )}
                  {/* Score */}
                  <span className="ml-auto px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700/50 text-gray-500 dark:text-gray-400 tabular-nums">
                    {Math.round(src.score * 100)}% match
                  </span>
                </div>
                <p className="font-medium text-gray-800 dark:text-gray-200 leading-tight">{src.title}</p>
                {src.summary && (
                  <p className="text-gray-500 dark:text-gray-400 leading-relaxed">
                    {src.summary.slice(0, 120)}{src.summary.length > 120 ? '…' : ''}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
