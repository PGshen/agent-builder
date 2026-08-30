import { apiClient } from './apiClient'

/** 后端敏感字段（env/headers 的 value）脱敏后的固定占位符，需要和 app/modules/mcp/masking.py 保持一致。 */
export const MASK_SENTINEL = '********'

export interface StdioMCPServerConfig {
  type: 'stdio'
  command: string
  args: string[]
  env: Record<string, string>
}

export interface SSEMCPServerConfig {
  type: 'sse'
  url: string
  headers: Record<string, string>
}

export interface HTTPMCPServerConfig {
  type: 'http'
  url: string
  headers: Record<string, string>
}

export type MCPServerConfig = StdioMCPServerConfig | SSEMCPServerConfig | HTTPMCPServerConfig
export type MCPServerType = MCPServerConfig['type']

export interface MCPServerListItem {
  id: string
  name: string
  status: string
  updated_at: string
}

export interface MCPServerDetail extends MCPServerListItem {
  config: MCPServerConfig
}

export function listMcpServers() {
  return apiClient.get<MCPServerListItem[]>('/mcp')
}

export function getMcpServer(id: string) {
  return apiClient.get<MCPServerDetail>(`/mcp/${id}`)
}

export function createMcpServer(name: string, config: MCPServerConfig) {
  return apiClient.post<MCPServerDetail>('/mcp', { name, config })
}

export function updateMcpServer(id: string, name: string, config: MCPServerConfig, status: string) {
  return apiClient.put<MCPServerDetail>(`/mcp/${id}`, { name, config, status })
}

export function deleteMcpServer(id: string) {
  return apiClient.delete<undefined>(`/mcp/${id}`)
}
