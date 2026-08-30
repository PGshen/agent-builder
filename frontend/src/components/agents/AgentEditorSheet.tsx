import { type FormEvent, useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { RepositoryListEditor, type RepoFormRow } from './RepositoryListEditor'
import { TransferList } from './TransferList'
import {
  PERMISSION_MODE_OPTIONS,
  createAgent,
  deleteAgent,
  getAgent,
  updateAgent,
  type AgentDetail,
  type AgentStatus,
  type PermissionMode,
} from '@/lib/agentsApi'
import { listSkills, type SkillListItem } from '@/lib/skillsApi'
import { listMcpServers, type MCPServerListItem } from '@/lib/mcpApi'

interface AgentEditorSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agentId: string | null
  onSaved: () => void
}

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

// 新建/编辑复用同一个表单，跟 MCP 抽屉一样是单表单（不像 Skill 需要"先建后编"两阶段）。
// 创建成功后抽屉原地切换成"编辑态"（不关闭），继续展示状态/绑定信息，呼应 T2.2 原本
// "创建后能看到初始化状态"的验收要求——只是载体从独立详情页换成了同一个抽屉。
export function AgentEditorSheet({ open, onOpenChange, agentId, onSaved }: AgentEditorSheetProps) {
  const [workingId, setWorkingId] = useState<string | null>(agentId)
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [permissionMode, setPermissionMode] = useState<PermissionMode>('default')
  const [refreshInterval, setRefreshInterval] = useState(30)
  const [skillIds, setSkillIds] = useState<string[]>([])
  const [mcpServerIds, setMcpServerIds] = useState<string[]>([])
  const [repositories, setRepositories] = useState<RepoFormRow[]>([])

  const [skills, setSkills] = useState<SkillListItem[] | null>(null)
  const [mcpServers, setMcpServers] = useState<MCPServerListItem[] | null>(null)

  const [loading, setLoading] = useState(agentId !== null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    let cancelled = false
    Promise.all([listSkills(), listMcpServers()]).then(([skillsResult, mcpResult]) => {
      if (cancelled) return
      setSkills(skillsResult.ok && skillsResult.data ? skillsResult.data : [])
      setMcpServers(mcpResult.ok && mcpResult.data ? mcpResult.data : [])
    })
    return () => {
      cancelled = true
    }
  }, [])

  function applyDetail(detail: AgentDetail) {
    setWorkingId(detail.id)
    setStatus(detail.status)
    setStatusMessage(detail.status_message)
    setName(detail.name)
    setDescription(detail.description ?? '')
    setPermissionMode(detail.permission_mode as PermissionMode)
    setRefreshInterval(detail.repo_refresh_interval_minutes)
    setSkillIds(detail.skills.map((s) => s.id))
    setMcpServerIds(detail.mcp_servers.map((m) => m.id))
    setRepositories(
      detail.repositories.map((repo) => ({
        id: repo.id,
        url: repo.url,
        branch: repo.branch ?? '',
        auth_type: repo.auth_type,
        auth_credential: repo.auth_credential ?? '',
      }))
    )
  }

  // 抽屉每次打开都靠外层 key={agentId-openSeq} 整体重新挂载拿到干净状态（同 Skill/MCP 抽屉模式）
  useEffect(() => {
    if (!agentId) return
    let cancelled = false
    getAgent(agentId).then((result) => {
      if (cancelled) return
      if (!result.ok || !result.data) {
        setLoading(false)
        setLoadError(result.status === 404 ? 'Agent 不存在' : '加载失败')
        return
      }
      applyDetail(result.data)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [agentId])

  async function handleRefreshStatus() {
    if (!workingId) return
    setRefreshing(true)
    const result = await getAgent(workingId)
    if (result.ok && result.data) {
      applyDetail(result.data)
    }
    setRefreshing(false)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return

    const body = {
      name: name.trim(),
      description: description.trim() || null,
      permission_mode: permissionMode,
      repo_refresh_interval_minutes: refreshInterval,
      skill_ids: skillIds,
      mcp_server_ids: mcpServerIds,
      repositories: repositories
        .filter((row) => row.url.trim())
        .map((row) => ({
          id: row.id,
          url: row.url.trim(),
          branch: row.branch.trim() || null,
          auth_type: row.auth_type,
          auth_credential: row.auth_type === 'none' ? null : row.auth_credential || null,
        })),
    }

    setSubmitting(true)
    setSaveError(null)
    setSaveMessage(null)

    const result = workingId ? await updateAgent(workingId, body) : await createAgent(body)

    setSubmitting(false)
    if (!result.ok || !result.data) {
      const detail = (result.data as unknown as { detail?: string } | undefined)?.detail
      setSaveError(detail ?? (result.status === 409 ? '同名 Agent 已存在，换一个名称再试' : '保存失败'))
      return
    }
    applyDetail(result.data)
    setSaveMessage(workingId ? '已保存' : '已创建')
    onSaved()
  }

  async function handleDelete() {
    if (!workingId) return
    if (!window.confirm(`确定删除 Agent「${name}」？此操作不可撤销。`)) return
    const result = await deleteAgent(workingId)
    if (!result.ok) {
      setSaveError('删除失败')
      return
    }
    onSaved()
    onOpenChange(false)
  }

  const isCreateMode = workingId === null

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        className="flex w-full flex-col gap-0 p-0"
        style={{ width: 'min(760px, 92vw)', maxWidth: 'min(760px, 92vw)' }}
      >
        <SheetHeader className="border-b">
          <div className="flex items-center gap-2">
            <SheetTitle>{isCreateMode ? '新建 Agent' : name}</SheetTitle>
            {!isCreateMode && status && (
              <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</Badge>
            )}
            {!isCreateMode && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleRefreshStatus}
                disabled={refreshing}
              >
                {refreshing ? '刷新中…' : '刷新状态'}
              </Button>
            )}
          </div>
          <SheetDescription>
            绑定 skills、MCP servers 和代码仓库，创建后 Workspace 会异步初始化。
          </SheetDescription>
        </SheetHeader>

        {loading && <p className="px-4 py-3 text-sm text-muted-foreground">加载中…</p>}
        {loadError && <p className="px-4 py-3 text-sm text-destructive">{loadError}</p>}

        {!loading && !loadError && (
          <form className="flex min-h-0 flex-1 flex-col overflow-y-auto" onSubmit={handleSubmit}>
            <div className="flex flex-1 flex-col gap-5 p-4">
              {!isCreateMode && status === 'failed' && statusMessage && (
                <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  初始化失败：{statusMessage}
                </p>
              )}

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-name">名称</Label>
                <Input
                  id="agent-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例如 code-review-agent"
                  required
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-description">能力描述</Label>
                <Textarea
                  id="agent-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="这个 Agent 擅长做什么、适合用在什么场景"
                  className="min-h-16"
                  style={{ fieldSizing: 'fixed' }}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>权限模式</Label>
                <div className="flex flex-wrap gap-1.5">
                  {PERMISSION_MODE_OPTIONS.map((option) => (
                    <Button
                      key={option.value}
                      type="button"
                      size="sm"
                      variant={permissionMode === option.value ? 'default' : 'outline'}
                      onClick={() => setPermissionMode(option.value)}
                    >
                      {option.label}
                    </Button>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  {PERMISSION_MODE_OPTIONS.find((o) => o.value === permissionMode)?.hint}
                </p>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="agent-refresh-interval">仓库刷新周期（分钟）</Label>
                <Input
                  id="agent-refresh-interval"
                  type="number"
                  min={1}
                  value={refreshInterval}
                  onChange={(e) => setRefreshInterval(Number(e.target.value) || 1)}
                  className="max-w-32"
                  required
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>绑定 Skills</Label>
                {skills === null ? (
                  <p className="text-sm text-muted-foreground">加载中…</p>
                ) : (
                  <TransferList
                    items={skills.map((s) => ({ id: s.id, label: s.name }))}
                    value={skillIds}
                    onChange={setSkillIds}
                    emptyHint="还没有可绑定的 Skill，先去 Skills 管理创建。"
                  />
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>绑定 MCP Servers</Label>
                {mcpServers === null ? (
                  <p className="text-sm text-muted-foreground">加载中…</p>
                ) : (
                  <TransferList
                    items={mcpServers.map((m) => ({ id: m.id, label: m.name }))}
                    value={mcpServerIds}
                    onChange={setMcpServerIds}
                    emptyHint="还没有可绑定的 MCP Server，先去 MCP 管理创建。"
                  />
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>代码仓库</Label>
                <RepositoryListEditor rows={repositories} onChange={setRepositories} />
              </div>
            </div>

            <SheetFooter className="flex-row items-center justify-between border-t">
              {isCreateMode ? (
                <span />
              ) : (
                <Button type="button" variant="destructive" size="sm" onClick={handleDelete}>
                  删除 Agent
                </Button>
              )}
              <div className="flex items-center gap-3">
                {saveError && <p className="text-sm text-destructive">{saveError}</p>}
                {saveMessage && !saveError && <p className="text-sm text-muted-foreground">{saveMessage}</p>}
                <Button type="submit" disabled={submitting}>
                  {submitting ? '保存中…' : isCreateMode ? '创建' : '保存'}
                </Button>
              </div>
            </SheetFooter>
          </form>
        )}
      </SheetContent>
    </Sheet>
  )
}
