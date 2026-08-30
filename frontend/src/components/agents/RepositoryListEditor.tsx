import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { AgentAuthType } from '@/lib/agentsApi'

export interface RepoFormRow {
  id?: string
  url: string
  branch: string
  auth_type: AgentAuthType
  // 明文（新输入）或后端脱敏占位符 "********"（未修改），auth_type=none 时不使用
  auth_credential: string
}

const AUTH_TYPE_OPTIONS: { value: AgentAuthType; label: string }[] = [
  { value: 'none', label: '无需鉴权' },
  { value: 'token', label: 'Token' },
  { value: 'ssh_key', label: 'SSH Key' },
]

interface RepositoryListEditorProps {
  rows: RepoFormRow[]
  onChange: (rows: RepoFormRow[]) => void
}

export function RepositoryListEditor({ rows, onChange }: RepositoryListEditorProps) {
  function updateRow(index: number, patch: Partial<RepoFormRow>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  function removeRow(index: number) {
    onChange(rows.filter((_, i) => i !== index))
  }

  function addRow() {
    onChange([...rows, { url: '', branch: '', auth_type: 'none', auth_credential: '' }])
  }

  return (
    <div className="flex flex-col gap-3">
      {rows.map((row, index) => (
        <div key={index} className="flex flex-col gap-2 rounded-lg border p-3">
          <div className="flex items-start gap-2">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor={`repo-url-${index}`}>仓库地址</Label>
              <Input
                id={`repo-url-${index}`}
                value={row.url}
                onChange={(e) => updateRow(index, { url: e.target.value })}
                placeholder="https://github.com/org/repo.git"
                className="font-mono text-sm"
                required
              />
            </div>
            <div className="flex w-40 flex-col gap-1.5">
              <Label htmlFor={`repo-branch-${index}`}>分支（可选）</Label>
              <Input
                id={`repo-branch-${index}`}
                value={row.branch}
                onChange={(e) => updateRow(index, { branch: e.target.value })}
                placeholder="main"
                className="font-mono text-sm"
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="删除仓库"
              className="mt-6"
              onClick={() => removeRow(index)}
            >
              <X className="size-3.5" />
            </Button>
          </div>
          <div className="flex items-end gap-2">
            <div className="flex w-40 flex-col gap-1.5">
              <Label>鉴权方式</Label>
              <Select
                value={row.auth_type}
                onValueChange={(value) => updateRow(index, { auth_type: value as AgentAuthType })}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {AUTH_TYPE_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {row.auth_type !== 'none' && (
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor={`repo-credential-${index}`}>
                  {row.auth_type === 'token' ? 'Access Token' : 'SSH 私钥'}
                </Label>
                <Input
                  id={`repo-credential-${index}`}
                  value={row.auth_credential}
                  onChange={(e) => updateRow(index, { auth_credential: e.target.value })}
                  placeholder="不修改则保持原值"
                  className="font-mono text-sm"
                  type={row.auth_type === 'token' ? 'password' : 'text'}
                />
              </div>
            )}
          </div>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" className="self-start" onClick={addRow}>
        添加仓库
      </Button>
    </div>
  )
}
