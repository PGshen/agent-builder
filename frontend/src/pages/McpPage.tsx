import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// 占位页面，业务内容见 docs/TASKS.md T1.5
export function McpPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>MCP 管理</CardTitle>
      </CardHeader>
      <CardContent className="text-muted-foreground">
        占位页面，后续在这里管理 MCP Server 配置。
      </CardContent>
    </Card>
  )
}
