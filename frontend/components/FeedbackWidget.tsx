'use client'

import { useState } from 'react'
import { submitFeedback } from '@/lib/api'

type Rating = 'correct' | 'can_be_better' | 'incorrect'

interface Props {
  sessionId: string
  messageIndex: number
}

const BUTTONS: { rating: Rating; label: string; icon: string; color: string }[] = [
  { rating: 'correct',       label: 'Correct',       icon: '✓', color: 'text-green-600 dark:text-green-400 border-green-300 dark:border-green-700 hover:bg-green-50 dark:hover:bg-green-950/30' },
  { rating: 'can_be_better', label: 'Can be better', icon: '≈', color: 'text-amber-600 dark:text-amber-400 border-amber-300 dark:border-amber-700 hover:bg-amber-50 dark:hover:bg-amber-950/30' },
  { rating: 'incorrect',     label: 'Incorrect',     icon: '✗', color: 'text-red-600 dark:text-red-400 border-red-300 dark:border-red-700 hover:bg-red-50 dark:hover:bg-red-950/30' },
]

export default function FeedbackWidget({ sessionId, messageIndex }: Props) {
  const [selected, setSelected] = useState<Rating | null>(null)
  const [comment, setComment] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit() {
    if (!selected) return
    setSubmitting(true)
    try {
      await submitFeedback(sessionId, messageIndex, selected, comment || undefined)
      setSubmitted(true)
    } catch { /* ignore */ }
    finally { setSubmitting(false) }
  }

  if (submitted) {
    return (
      <p className="text-xs text-green-600 dark:text-green-400 mt-2">
        Thank you for your feedback
      </p>
    )
  }

  return (
    <div className="mt-2 space-y-2">
      <div className="flex items-center gap-1.5">
        {BUTTONS.map(({ rating, label, icon, color }) => (
          <button
            key={rating}
            disabled={submitted}
            onClick={() => setSelected(rating)}
            className={`px-2.5 py-1 rounded-md text-xs font-medium border transition-colors
              ${selected === rating
                ? 'bg-gray-100 dark:bg-gray-700 border-gray-400 dark:border-gray-500'
                : `bg-transparent border-gray-200 dark:border-gray-700 ${color}`
              }`}
          >
            {icon} {label}
          </button>
        ))}
      </div>

      {selected && (
        <div className="space-y-1.5">
          <textarea
            value={comment}
            onChange={e => setComment(e.target.value)}
            placeholder="Optional comment…"
            rows={2}
            className="w-full text-xs px-2.5 py-1.5 rounded-md border border-gray-200 dark:border-gray-700
                       bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300
                       placeholder-gray-400 resize-none focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="px-3 py-1 rounded-md bg-blue-600 hover:bg-blue-700 disabled:opacity-50
                       text-white text-xs font-medium transition-colors"
          >
            {submitting ? 'Submitting…' : 'Submit feedback'}
          </button>
        </div>
      )}
    </div>
  )
}
