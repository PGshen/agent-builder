import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { SkillEditorSheet } from '@/components/skills/SkillEditorSheet'
import { listSkills, type SkillListItem } from '@/lib/skillsApi'

export function SkillsPage() {
  const [skills, setSkills] = useState<SkillListItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  // 抽屉每次打开都要在一份全新的状态里工作（不能沿用上次打开时的残留编辑内容），
  // 用 key={`${editingId}-${openSeq}`} 强制 SkillEditorSheet 每次打开都重新挂载
  const [openSeq, setOpenSeq] = useState(0)

  async function reload() {
    const result = await listSkills()
    if (!result.ok || !result.data) {
      setError('加载 Skill 列表失败')
      return
    }
    setError(null)
    setSkills(result.data)
  }

  useEffect(() => {
    let cancelled = false
    listSkills().then((result) => {
      if (cancelled) return
      if (!result.ok || !result.data) {
        setError('加载 Skill 列表失败')
        return
      }
      setError(null)
      setSkills(result.data)
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
        <CardTitle>Skills 管理</CardTitle>
        <Button size="sm" onClick={openCreate}>
          新建 Skill
        </Button>
      </CardHeader>
      <CardContent>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!error && skills === null && <p className="text-sm text-muted-foreground">加载中…</p>}
        {skills !== null && skills.length === 0 && (
          <p className="text-sm text-muted-foreground">还没有 Skill，点击右上角新建一个。</p>
        )}
        {skills !== null && skills.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>版本</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>更新时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {skills.map((skill) => (
                <TableRow key={skill.id}>
                  <TableCell>
                    <button
                      type="button"
                      className="font-medium hover:underline"
                      onClick={() => openEdit(skill.id)}
                    >
                      {skill.name}
                    </button>
                  </TableCell>
                  <TableCell>
                    v{skill.active_version}
                    {skill.active_version !== skill.version && (
                      <span className="ml-1 text-xs text-muted-foreground">（最新 v{skill.version}）</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{skill.status}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(skill.updated_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <SkillEditorSheet
        key={`${editingId ?? 'create'}-${openSeq}`}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        skillId={editingId}
        onSaved={reload}
      />
    </Card>
  )
}
