import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { logout as logoutRequest } from '@/lib/apiClient'
import { clearAuthToken } from '@/lib/auth'
import { BackendStatus } from './BackendStatus'

const NAV_ITEMS = [
  { to: '/skills', label: 'Skills' },
  { to: '/mcp', label: 'MCP' },
  { to: '/agents', label: 'Agent Builder' },
  { to: '/conversations', label: '对话' },
]

export function AppLayout() {
  const navigate = useNavigate()

  async function handleLogout() {
    await logoutRequest()
    clearAuthToken()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <div className="flex items-center gap-8">
          <strong className="text-base font-heading">AgentBuilder</strong>
          <nav className="flex gap-4">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'text-sm text-muted-foreground transition-colors hover:text-foreground',
                    isActive && 'font-medium text-foreground'
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <BackendStatus />
          <Button variant="ghost" size="sm" onClick={handleLogout}>
            登出
          </Button>
        </div>
      </header>
      <main className="flex-1 p-6">
        <Outlet />
      </main>
    </div>
  )
}
