import { apiClient } from './apiClient'

/** 仓库凭证脱敏后的固定占位符，需要和 app/modules/agents/masking.py::MASK_SENTINEL 保持一致。 */
export const REPO_CREDENTIAL_MASK = '********'

export type AgentAuthType = 'none' | 'token' | 'ssh_key'

/**
 * 对齐 Claude Agent SDK 的 permissionMode 枚举，v1 直接暴露 SDK 原生取值，不做额外产品层封装
 * （TECH_DESIGN 8 "权限模式在产品层的可配置粒度" 待确认项，在本任务 T2.2 落地时这样决定）。
 */
export type PermissionMode = 'default' | 'acceptEdits' | 'bypassPermissions' | 'plan'

export const PERMISSION_MODE_OPTIONS: { value: PermissionMode; label: string; hint: string }[] = [
  { value: 'default', label: 'default', hint: '每次工具调用都按常规权限规则询问确认' },
  { value: 'acceptEdits', label: 'acceptEdits', hint: '自动接受文件编辑类操作，其余仍需确认' },
  { value: 'bypassPermissions', label: 'bypassPermissions', hint: '跳过权限确认，完全自主执行（谨慎使用）' },
  { value: 'plan', label: 'plan', hint: '仅规划，不实际执行改动' },
]

export interface AgentRepositoryInput {
  id?: string
  url: string
  branch: string | null
  auth_type: AgentAuthType
  auth_credential: string | null
}

export interface AgentRepositoryDetail {
  id: string
  url: string
  branch: string | null
  auth_type: AgentAuthType
  // 打码值（有凭证时）或 null，从不是明文
  auth_credential: string | null
  position: number
  last_synced_at: string | null
  last_synced_commit: string | null
}

export interface BoundSkill {
  id: string
  name: string
}

export interface BoundMCPServer {
  id: string
  name: string
}

/** initializing（初始化中）/ ready（就绪）/ failed（失败），T2.4 状态流转 */
export type AgentStatus = 'initializing' | 'ready' | 'failed'

export interface AgentListItem {
  id: string
  name: string
  description: string | null
  status: AgentStatus
  permission_mode: string
  repo_refresh_interval_minutes: number
  updated_at: string
  skill_count: number
  mcp_server_count: number
  repository_count: number
}

export interface AgentDetail {
  id: string
  name: string
  description: string | null
  workspace_id: string
  permission_mode: string
  repo_refresh_interval_minutes: number
  status: AgentStatus
  status_message: string | null
  updated_at: string
  skills: BoundSkill[]
  mcp_servers: BoundMCPServer[]
  repositories: AgentRepositoryDetail[]
}

export interface AgentFormInput {
  name: string
  description: string | null
  permission_mode: string
  repo_refresh_interval_minutes: number
  skill_ids: string[]
  mcp_server_ids: string[]
  repositories: AgentRepositoryInput[]
}

export function listAgents() {
  return apiClient.get<AgentListItem[]>('/agents')
}

export function getAgent(id: string) {
  return apiClient.get<AgentDetail>(`/agents/${id}`)
}

export function createAgent(body: AgentFormInput) {
  return apiClient.post<AgentDetail>('/agents', body)
}

export function updateAgent(id: string, body: AgentFormInput) {
  return apiClient.put<AgentDetail>(`/agents/${id}`, body)
}

export function deleteAgent(id: string) {
  return apiClient.delete<undefined>(`/agents/${id}`)
}
