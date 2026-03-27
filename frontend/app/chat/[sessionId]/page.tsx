'use client'

import { getEngineerId } from '@/lib/auth'
import ChatWindow from '@/components/ChatWindow'

export default function SessionPage({ params }: { params: { sessionId: string } }) {
  const engineerId = getEngineerId() ?? ''
  return <ChatWindow initialSessionId={params.sessionId} engineerId={engineerId} />
}
