import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './layout/AppLayout'
import { RequireAuth } from './layout/RequireAuth'
import { LoginPage } from './pages/LoginPage'
import { SkillsPage } from './pages/SkillsPage'
import { McpPage } from './pages/McpPage'
import { AgentBuilderPage } from './pages/AgentBuilderPage'
import { ConversationPage } from './pages/ConversationPage'

export default function App() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/skills" replace />} />
        <Route path="skills" element={<SkillsPage />} />
        <Route path="mcp" element={<McpPage />} />
        <Route path="agents" element={<AgentBuilderPage />} />
        <Route path="conversations" element={<ConversationPage />} />
      </Route>
    </Routes>
  )
}
