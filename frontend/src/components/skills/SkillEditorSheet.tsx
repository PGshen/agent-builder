import { type FormEvent, useEffect, useState } from 'react'
import { History } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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
  activateSkillVersion,
  buildSkillTemplate,
  createSkillFromFiles,
  deleteSkill,
  getSkill,
  updateSkill,
  type SkillDetail,
} from '@/lib/skillsApi'
import { SkillFileTree } from './SkillFileTree'

interface SkillEditorSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  skillId: string | null
  onSaved: () => void
}

// 新建走"从模板创建"：先填名称/描述生成最小 SKILL.md 并提交，创建成功后这个抽屉原地
// 切换成编辑态（不关闭、不跳转），用户可以继续在同一个抽屉里加文件、改内容、保存。
export function SkillEditorSheet({ open, onOpenChange, skillId, onSaved }: SkillEditorSheetProps) {
  const isCreateMode = skillId === null

  const [workingId, setWorkingId] = useState<string | null>(skillId)
  const [meta, setMeta] = useState<Omit<SkillDetail, 'files'> | null>(null)
  const [files, setFiles] = useState<Record<string, string>>({})
  const [selectedPath, setSelectedPath] = useState<string | null>(null)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function loadDetail(id: string) {
    const result = await getSkill(id)
    if (!result.ok || !result.data) {
      setLoadError(result.status === 404 ? 'Skill 不存在' : '加载失败')
      return
    }
    const { files: loadedFiles, ...loadedMeta } = result.data
    setWorkingId(id)
    setMeta(loadedMeta)
    setFiles(loadedFiles)
    setSelectedPath((current) => (current && current in loadedFiles ? current : Object.keys(loadedFiles).sort()[0] ?? null))
  }

  // 这个组件靠外层 `key={editingId-openSeq}` 在每次打开时整体重新挂载来拿到一份干净的初始状态
  // （见 SkillsPage.tsx），这里只需要在编辑态时把详情拉回来，不需要再手动重置一遍 state。
  useEffect(() => {
    if (!skillId) return
    let cancelled = false
    getSkill(skillId).then((result) => {
      if (cancelled) return
      if (!result.ok || !result.data) {
        setLoadError(result.status === 404 ? 'Skill 不存在' : '加载失败')
        return
      }
      const { files: loadedFiles, ...loadedMeta } = result.data
      setMeta(loadedMeta)
      setFiles(loadedFiles)
      setSelectedPath(Object.keys(loadedFiles).sort()[0] ?? null)
    })
    return () => {
      cancelled = true
    }
  }, [skillId])

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return

    setSubmitting(true)
    setSaveError(null)
    const template = buildSkillTemplate(name.trim(), description.trim())
    const result = await createSkillFromFiles(name.trim(), template)

    if (!result.ok || !result.data) {
      setSubmitting(false)
      setSaveError(result.status === 409 ? '同名 Skill 已存在，换一个名称再试' : '创建失败，请检查名称是否合法后重试')
      return
    }

    await loadDetail(result.data.id)
    setSubmitting(false)
    onSaved()
  }

  async function handleSave() {
    if (!workingId) return
    setSubmitting(true)
    setSaveError(null)
    setSaveMessage(null)

    const result = await updateSkill(workingId, files)

    if (!result.ok || !result.data) {
      setSubmitting(false)
      const detail = (result.data as unknown as { detail?: string } | undefined)?.detail
      setSaveError(detail ?? '保存失败')
      return
    }
    await loadDetail(workingId)
    setSubmitting(false)
    setSaveMessage(`已保存为新版本 v${result.data.version}`)
    onSaved()
  }

  async function handleActivateVersion(version: number) {
    if (!workingId) return
    setSaveError(null)
    setSaveMessage(null)
    const result = await activateSkillVersion(workingId, version)
    if (!result.ok) {
      setSaveError('切换版本失败')
      return
    }
    await loadDetail(workingId)
    setSaveMessage(`已切换到 v${version}`)
    onSaved()
  }

  async function handleDeleteSkill() {
    if (!workingId || !meta) return
    if (!window.confirm(`确定删除 Skill「${meta.name}」？此操作不可撤销，会连同它的所有历史版本一起删除。`)) return
    const result = await deleteSkill(workingId)
    if (!result.ok) {
      setSaveError('删除失败')
      return
    }
    onSaved()
    onOpenChange(false)
  }

  const showEditor = workingId !== null && meta !== null
  const sortedVersions = meta ? [...meta.versions].sort((a, b) => b.version - a.version) : []

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        className="flex w-full flex-col gap-0 p-0"
        style={{ width: '85vw', maxWidth: '85vw' }}
      >
        {/* shadcn 的 SheetContent 基础 class 里 `data-[side=right]:sm:max-w-sm` 带了属性选择器，
            比普通 `sm:max-w-*` 工具类特异性更高，className 覆盖不掉，改用内联 style 强制生效 */}
        <SheetHeader className="border-b">
          {showEditor ? (
            <div className="flex items-center gap-2">
              <SheetTitle>{meta.name}</SheetTitle>
              <Badge variant="secondary">v{meta.active_version}</Badge>
              {meta.active_version !== meta.version && (
                <Badge variant="outline" className="text-muted-foreground">
                  最新 v{meta.version}
                </Badge>
              )}
              <Badge variant="outline">{meta.status}</Badge>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon-sm" aria-label="历史版本">
                    <History className="size-3.5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuLabel>历史版本</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {sortedVersions.map((entry) => (
                    <DropdownMenuItem
                      key={entry.version}
                      disabled={entry.version === meta.active_version}
                      onSelect={() => handleActivateVersion(entry.version)}
                      className="flex flex-col items-start gap-0"
                    >
                      <span className="flex items-center gap-1.5">
                        v{entry.version}
                        {entry.version === meta.active_version && (
                          <Badge variant="secondary" className="text-[0.65rem]">
                            当前
                          </Badge>
                        )}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {new Date(entry.created_at).toLocaleString()}
                      </span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ) : (
            <SheetTitle>新建 Skill</SheetTitle>
          )}
          <SheetDescription>
            {showEditor ? '浏览左侧文件树，选中文件编辑内容，改完点保存（保存会新增一个版本，不会覆盖旧版本）。' : '填写名称和描述，生成最小可用的 SKILL.md。'}
          </SheetDescription>
        </SheetHeader>

        {loadError && <p className="px-4 py-3 text-sm text-destructive">{loadError}</p>}

        {!loadError && !showEditor && isCreateMode && (
          <form className="flex flex-col gap-4 p-4" onSubmit={handleCreate}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="skill-name">名称</Label>
              <Input
                id="skill-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如 pdf-report-generator"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="skill-description">描述</Label>
              <Input
                id="skill-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="这个 Skill 用来做什么"
              />
            </div>
            {saveError && <p className="text-sm text-destructive">{saveError}</p>}
            <Button type="submit" disabled={submitting}>
              {submitting ? '创建中…' : '创建'}
            </Button>
          </form>
        )}

        {!loadError && showEditor && (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4">
            <div className="grid min-h-0 flex-1 grid-cols-[260px_1fr] gap-4">
              <div className="min-h-0 overflow-y-auto rounded-lg border p-1.5">
                <SkillFileTree
                  files={files}
                  selectedPath={selectedPath}
                  onSelectFile={setSelectedPath}
                  onFilesChange={setFiles}
                />
              </div>

              <div className="flex min-h-0 flex-col gap-2">
                {selectedPath ? (
                  <>
                    <p className="font-mono text-xs text-muted-foreground">{selectedPath}</p>
                    <Textarea
                      value={files[selectedPath] ?? ''}
                      onChange={(e) => setFiles((prev) => ({ ...prev, [selectedPath]: e.target.value }))}
                      className="min-h-0 flex-1 resize-none overflow-y-auto font-mono text-sm"
                      style={{ fieldSizing: 'fixed' }}
                    />
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">从左侧选择一个文件查看/编辑内容。</p>
                )}
              </div>
            </div>
          </div>
        )}

        {!loadError && showEditor && (
          <SheetFooter className="flex-row items-center justify-between border-t">
            <Button variant="destructive" size="sm" onClick={handleDeleteSkill}>
              删除 Skill
            </Button>
            <div className="flex items-center gap-3">
              {saveError && <p className="text-sm text-destructive">{saveError}</p>}
              {saveMessage && !saveError && <p className="text-sm text-muted-foreground">{saveMessage}</p>}
              <Button onClick={handleSave} disabled={submitting}>
                {submitting ? '保存中…' : '保存'}
              </Button>
            </div>
          </SheetFooter>
        )}
      </SheetContent>
    </Sheet>
  )
}
