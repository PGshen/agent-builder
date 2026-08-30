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
import {
  createMcpServer,
  deleteMcpServer,
  getMcpServer,
  updateMcpServer,
  type MCPServerType,
} from '@/lib/mcpApi'
import { pairsToRecord, recordToPairs, type KeyValuePair } from '@/lib/keyValuePairs'
import { KeyValueEditor } from './KeyValueEditor'

interface McpEditorSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  mcpId: string | null
  onSaved: () => void
}

const TYPE_OPTIONS: { value: MCPServerType; label: string; hint: string }[] = [
  { value: 'stdio', label: 'stdio', hint: '本地起子进程，通过标准输入输出通信' },
  { value: 'sse', label: 'sse', hint: '远程 Server-Sent Events 端点' },
  { value: 'http', label: 'http', hint: '远程流式 HTTP 端点' },
]

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: 'active', label: '启用' },
  { value: 'disabled', label: '禁用' },
]

// 新建/编辑复用同一个表单：MCP 配置不像 Skill 有文件树那样的两阶段流程，
// 字段随 type 切换联动显示（stdio 显示 command/args/env，sse/http 显示 url/headers）。
export function McpEditorSheet({ open, onOpenChange, mcpId, onSaved }: McpEditorSheetProps) {
  const isCreateMode = mcpId === null

  const [name, setName] = useState('')
  const [status, setStatus] = useState('active')
  const [type, setType] = useState<MCPServerType>('stdio')
  const [command, setCommand] = useState('')
  const [argsText, setArgsText] = useState('')
  const [envPairs, setEnvPairs] = useState<KeyValuePair[]>([])
  const [url, setUrl] = useState('')
  const [headersPairs, setHeadersPairs] = useState<KeyValuePair[]>([])

  const [loading, setLoading] = useState(!isCreateMode)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // 这个组件靠外层 key={mcpId-openSeq} 在每次打开时整体重新挂载来拿到干净状态（同 SkillEditorSheet 模式）
  useEffect(() => {
    if (!mcpId) return
    let cancelled = false
    getMcpServer(mcpId).then((result) => {
      if (cancelled) return
      if (!result.ok || !result.data) {
        setLoading(false)
        setLoadError(result.status === 404 ? 'MCP Server 不存在' : '加载失败')
        return
      }
      const detail = result.data
      setName(detail.name)
      setStatus(detail.status)
      setType(detail.config.type)
      if (detail.config.type === 'stdio') {
        setCommand(detail.config.command)
        setArgsText(detail.config.args.join('\n'))
        setEnvPairs(recordToPairs(detail.config.env))
      } else {
        setUrl(detail.config.url)
        setHeadersPairs(recordToPairs(detail.config.headers))
      }
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [mcpId])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return

    const config =
      type === 'stdio'
        ? {
            type: 'stdio' as const,
            command: command.trim(),
            args: argsText
              .split('\n')
              .map((line) => line.trim())
              .filter(Boolean),
            env: pairsToRecord(envPairs),
          }
        : {
            type,
            url: url.trim(),
            headers: pairsToRecord(headersPairs),
          }

    setSubmitting(true)
    setSaveError(null)

    const result = isCreateMode
      ? await createMcpServer(name.trim(), config)
      : await updateMcpServer(mcpId, name.trim(), config, status)

    setSubmitting(false)
    if (!result.ok || !result.data) {
      const detail = (result.data as unknown as { detail?: string } | undefined)?.detail
      setSaveError(detail ?? (result.status === 409 ? '同名 MCP Server 已存在，换一个名称再试' : '保存失败'))
      return
    }
    onSaved()
    onOpenChange(false)
  }

  async function handleDelete() {
    if (!mcpId) return
    if (!window.confirm(`确定删除 MCP Server「${name}」？此操作不可撤销。`)) return
    const result = await deleteMcpServer(mcpId)
    if (!result.ok) {
      setSaveError('删除失败')
      return
    }
    onSaved()
    onOpenChange(false)
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-0 p-0 sm:max-w-xl">
        <SheetHeader className="border-b">
          <div className="flex items-center gap-2">
            <SheetTitle>{isCreateMode ? '新建 MCP Server' : name}</SheetTitle>
            {!isCreateMode && <Badge variant="outline">{status === 'active' ? '启用' : '禁用'}</Badge>}
          </div>
          <SheetDescription>
            配置结构对齐 Claude Agent SDK 的 mcpServers 选项；env/headers 里的 value 是敏感信息，已脱敏展示。
          </SheetDescription>
        </SheetHeader>

        {loading && <p className="px-4 py-3 text-sm text-muted-foreground">加载中…</p>}
        {loadError && <p className="px-4 py-3 text-sm text-destructive">{loadError}</p>}

        {!loading && !loadError && (
          <form className="flex min-h-0 flex-1 flex-col overflow-y-auto" onSubmit={handleSubmit}>
            <div className="flex flex-1 flex-col gap-4 p-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="mcp-name">名称</Label>
                <Input
                  id="mcp-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例如 filesystem-mcp"
                  required
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>类型</Label>
                <div className="flex gap-1.5">
                  {TYPE_OPTIONS.map((option) => (
                    <Button
                      key={option.value}
                      type="button"
                      size="sm"
                      variant={type === option.value ? 'default' : 'outline'}
                      onClick={() => setType(option.value)}
                    >
                      {option.label}
                    </Button>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  {TYPE_OPTIONS.find((o) => o.value === type)?.hint}
                </p>
              </div>

              {!isCreateMode && (
                <div className="flex flex-col gap-1.5">
                  <Label>状态</Label>
                  <div className="flex gap-1.5">
                    {STATUS_OPTIONS.map((option) => (
                      <Button
                        key={option.value}
                        type="button"
                        size="sm"
                        variant={status === option.value ? 'default' : 'outline'}
                        onClick={() => setStatus(option.value)}
                      >
                        {option.label}
                      </Button>
                    ))}
                  </div>
                </div>
              )}

              {type === 'stdio' ? (
                <>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="mcp-command">命令</Label>
                    <Input
                      id="mcp-command"
                      value={command}
                      onChange={(e) => setCommand(e.target.value)}
                      placeholder="例如 npx"
                      className="font-mono text-sm"
                      required
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="mcp-args">参数（每行一个）</Label>
                    <Textarea
                      id="mcp-args"
                      value={argsText}
                      onChange={(e) => setArgsText(e.target.value)}
                      placeholder={'-y\n@some/mcp-server'}
                      className="min-h-16 font-mono text-sm"
                      style={{ fieldSizing: 'fixed' }}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label>环境变量</Label>
                    <KeyValueEditor
                      pairs={envPairs}
                      onChange={setEnvPairs}
                      addLabel="添加环境变量"
                      keyPlaceholder="API_KEY"
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="mcp-url">URL</Label>
                    <Input
                      id="mcp-url"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      placeholder="https://example.com/mcp"
                      className="font-mono text-sm"
                      required
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label>请求头</Label>
                    <KeyValueEditor
                      pairs={headersPairs}
                      onChange={setHeadersPairs}
                      addLabel="添加请求头"
                      keyPlaceholder="Authorization"
                    />
                  </div>
                </>
              )}
            </div>

            <SheetFooter className="flex-row items-center justify-between border-t">
              {isCreateMode ? (
                <span />
              ) : (
                <Button type="button" variant="destructive" size="sm" onClick={handleDelete}>
                  删除
                </Button>
              )}
              <div className="flex items-center gap-3">
                {saveError && <p className="text-sm text-destructive">{saveError}</p>}
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
