'use client'

import { useSearchParams } from 'next/navigation'
import { getEngineerId } from '@/lib/auth'
import ChatWindow from '@/components/ChatWindow'

export default function ChatPage() {
  const searchParams = useSearchParams()
  // Every unique value of ?new= mounts a completely fresh ChatWindow.
  // This means "New Chat" always clears messages even when already on /chat.
  const chatKey = searchParams.get('new') ?? 'default'
  const engineerId = getEngineerId() ?? ''
  return <ChatWindow key={chatKey} engineerId={engineerId} />
}
