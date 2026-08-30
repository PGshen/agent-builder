import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { McpEditorSheet } from '@/components/mcp/McpEditorSheet'
import { listMcpServers, type MCPServerListItem } from '@/lib/mcpApi'

export function McpPage() {
  const [mcpServers, setMcpServers] = useState<MCPServerListItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  // 抽屉每次打开都要在一份全新的状态里工作，用 key={editingId-openSeq} 强制重新挂载（同 Skills 页模式）
  const [openSeq, setOpenSeq] = useState(0)

  async function reload() {
    const result = await listMcpServers()
    if (!result.ok || !result.data) {
      setError('加载 MCP Server 列表失败')
      return
    }
    setError(null)
    setMcpServers(result.data)
  }

  useEffect(() => {
    let cancelled = false
    listMcpServers().then((result) => {
      if (cancelled) return
      if (!result.ok || !result.data) {
        setError('加载 MCP Server 列表失败')
        return
      }
      setError(null)
      setMcpServers(result.data)
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
        <CardTitle>MCP 管理</CardTitle>
        <Button size="sm" onClick={openCreate}>
          新建 MCP Server
        </Button>
      </CardHeader>
      <CardContent>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!error && mcpServers === null && <p className="text-sm text-muted-foreground">加载中…</p>}
        {mcpServers !== null && mcpServers.length === 0 && (
          <p className="text-sm text-muted-foreground">还没有 MCP Server，点击右上角新建一个。</p>
        )}
        {mcpServers !== null && mcpServers.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>更新时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mcpServers.map((mcpServer) => (
                <TableRow key={mcpServer.id}>
                  <TableCell>
                    <button
                      type="button"
                      className="font-medium hover:underline"
                      onClick={() => openEdit(mcpServer.id)}
                    >
                      {mcpServer.name}
                    </button>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{mcpServer.status === 'active' ? '启用' : '禁用'}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(mcpServer.updated_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <McpEditorSheet
        key={`${editingId ?? 'create'}-${openSeq}`}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        mcpId={editingId}
        onSaved={reload}
      />
    </Card>
  )
}
