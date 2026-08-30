import { clearAuthToken, getAuthToken } from './auth'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8080'

export interface ApiResult<T> {
  ok: boolean
  status: number
  data: T | undefined
}

/**
 * 统一请求封装。不对非 2xx 状态抛异常——例如 /health 在依赖不可用时会返回 503 但仍带有效 body，
 * 调用方根据 ok/status 自行决定如何展示，而不是被当成网络异常吞掉。
 */
export async function apiRequest<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  const headers = new Headers(init?.headers)
  // FormData 请求（文件上传）不手动设 Content-Type：浏览器需要自己生成带 boundary 的
  // multipart/form-data 头，手动设置反而会丢掉 boundary 导致后端解析不出表单字段
  if (init?.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getAuthToken()
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
  if (response.status === 401) {
    // token 缺失/过期/被撤销：清掉本地登录态，下次路由守卫检查时会跳回登录页
    clearAuthToken()
  }
  const data = (await response.json().catch(() => undefined)) as T | undefined

  return { ok: response.ok, status: response.status, data }
}

export const apiClient = {
  get: <T,>(path: string) => apiRequest<T>(path, { method: 'GET' }),
  post: <T,>(path: string, body?: unknown) =>
    apiRequest<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T,>(path: string, body?: unknown) =>
    apiRequest<T>(path, { method: 'PUT', body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T,>(path: string) => apiRequest<T>(path, { method: 'DELETE' }),
  postForm: <T,>(path: string, form: FormData) => apiRequest<T>(path, { method: 'POST', body: form }),
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  timestamp: string
  dependencies: Record<string, Record<string, boolean>>
}

export function getHealth() {
  return apiClient.get<HealthResponse>('/health')
}

export interface LoginResponse {
  token: string
  expires_in: number
}

export function login(username: string, password: string) {
  return apiClient.post<LoginResponse>('/auth/login', { username, password })
}

export function logout() {
  return apiClient.post<undefined>('/auth/logout')
}
