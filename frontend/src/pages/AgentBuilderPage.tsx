import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// 占位页面，业务内容见 docs/TASKS.md T2.2
export function AgentBuilderPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Agent Builder</CardTitle>
      </CardHeader>
      <CardContent className="text-muted-foreground">
        占位页面，后续在这里创建/编辑 Agent，绑定 skills、MCP、代码仓库。
      </CardContent>
    </Card>
  )
}
