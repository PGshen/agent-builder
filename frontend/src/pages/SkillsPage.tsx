import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// 占位页面，业务内容见 docs/TASKS.md T1.3
export function SkillsPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Skills 管理</CardTitle>
      </CardHeader>
      <CardContent className="text-muted-foreground">
        占位页面，后续在这里管理 Skill 的增删改查。
      </CardContent>
    </Card>
  )
}
