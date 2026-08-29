import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// 占位页面，业务内容见 docs/TASKS.md T5.1
export function ConversationPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>对话</CardTitle>
      </CardHeader>
      <CardContent className="text-muted-foreground">
        占位页面，后续在这里选择 Agent 并进行对话。
      </CardContent>
    </Card>
  )
}
