import { zipSync } from 'fflate'
import { apiClient } from './apiClient'

export interface SkillListItem {
  id: string
  name: string
  version: number
  active_version: number
  status: string
  updated_at: string
}

export interface SkillVersionEntry {
  version: number
  object_key: string
  created_at: string
}

export interface SkillDetail extends SkillListItem {
  files: Record<string, string>
  versions: SkillVersionEntry[]
}

export function listSkills() {
  return apiClient.get<SkillListItem[]>('/skills')
}

export function getSkill(id: string) {
  return apiClient.get<SkillDetail>(`/skills/${id}`)
}

export function updateSkill(id: string, files: Record<string, string>) {
  return apiClient.put<SkillListItem>(`/skills/${id}`, { files })
}

export function deleteSkill(id: string) {
  return apiClient.delete<undefined>(`/skills/${id}`)
}

export function activateSkillVersion(id: string, version: number) {
  return apiClient.post<SkillListItem>(`/skills/${id}/versions/${version}/activate`)
}

/** 把文本文件树打包成 zip 并调用创建接口（后端只接受 zip 上传，见 T1.2 决策记录）。 */
export function createSkillFromFiles(name: string, files: Record<string, string>) {
  const encoder = new TextEncoder()
  const zipInput: Record<string, Uint8Array> = {}
  for (const [path, content] of Object.entries(files)) {
    zipInput[path] = encoder.encode(content)
  }
  const zipped = zipSync(zipInput)
  const blob = new Blob([zipped], { type: 'application/zip' })

  const form = new FormData()
  form.set('name', name)
  form.set('file', blob, 'skill.zip')
  return apiClient.postForm<SkillListItem>('/skills', form)
}

/** 新建 Skill 时的最小模板：一个符合规范的 SKILL.md（后端要求根路径必须有这个文件）。 */
export function buildSkillTemplate(name: string, description: string): Record<string, string> {
  return {
    'SKILL.md': `---\nname: ${name}\ndescription: ${description || name}\n---\n\n# ${name}\n\n在这里描述这个 Skill 的用途和使用方式。\n`,
  }
}
