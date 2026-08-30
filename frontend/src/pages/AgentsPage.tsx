import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { AgentEditorSheet } from '@/components/agents/AgentEditorSheet'
import { listAgents, type AgentListItem, type AgentStatus } from '@/lib/agentsApi'

const STATUS_LABEL: Record<AgentStatus, string> = {
  initializing: '初始化中',
  ready: '就绪',
  failed: '失败',
}

const STATUS_VARIANT: Record<AgentStatus, 'secondary' | 'default' | 'destructive'> = {
  initializing: 'secondary',
  ready: 'default',
  failed: 'destructive',
}

export function AgentsPage() {
  const [agents, setAgents] = useState<AgentListItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  // 抽屉每次打开都要在一份全新的状态里工作，用 key={editingId-openSeq} 强制重新挂载（同 Skills/MCP 页模式）
  const [openSeq, setOpenSeq] = useState(0)

  async function reload() {
    const result = await listAgents()
    if (!result.ok || !result.data) {
      setError('加载 Agent 列表失败')
      return
    }
    setError(null)
    setAgents(result.data)
  }

  useEffect(() => {
    let cancelled = false
    listAgents().then((result) => {
      if (cancelled) return
      if (!result.ok || !result.data) {
        setError('加载 Agent 列表失败')
        return
      }
      setError(null)
      setAgents(result.data)
    })
    return () => {
      cancelled = true
    }
  }, [])

  function openCreate() {
    setEditingId(null)
    setOpenSeq((n) => n + 1)
    setSheetOpen(true)
  }

  function openEdit(id: string) {
    setEditingId(id)
    setOpenSeq((n) => n + 1)
    setSheetOpen(true)
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Agent Builder</CardTitle>
        <Button size="sm" onClick={openCreate}>
          新建 Agent
        </Button>
      </CardHeader>
      <CardContent>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!error && agents === null && <p className="text-sm text-muted-foreground">加载中…</p>}
        {agents !== null && agents.length === 0 && (
          <p className="text-sm text-muted-foreground">还没有 Agent，点击右上角新建一个。</p>
        )}
        {agents !== null && agents.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>权限模式</TableHead>
                <TableHead>绑定</TableHead>
                <TableHead>更新时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agents.map((agent) => (
                <TableRow key={agent.id}>
                  <TableCell>
                    <button
                      type="button"
                      className="font-medium hover:underline"
                      onClick={() => openEdit(agent.id)}
                    >
                      {agent.name}
                    </button>
                    {agent.description && (
                      <p className="max-w-xs truncate text-xs text-muted-foreground">{agent.description}</p>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANT[agent.status]}>{STATUS_LABEL[agent.status]}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{agent.permission_mode}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {agent.skill_count} skills · {agent.mcp_server_count} MCP · {agent.repository_count} 仓库
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(agent.updated_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <AgentEditorSheet
        key={`${editingId ?? 'create'}-${openSeq}`}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        agentId={editingId}
        onSaved={reload}
      />
    </Card>
  )
}
