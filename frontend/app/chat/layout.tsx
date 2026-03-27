'use client'

import AuthGuard from '@/components/AuthGuard'
import SessionSidebar from '@/components/SessionSidebar'

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden bg-white dark:bg-gray-950">
        {/* Sidebar */}
        <div className="w-64 shrink-0 h-full overflow-hidden">
          <SessionSidebar />
        </div>
        {/* Main */}
        <main className="flex-1 min-w-0 h-full overflow-hidden flex flex-col">
          {children}
        </main>
      </div>
    </AuthGuard>
  )
}
