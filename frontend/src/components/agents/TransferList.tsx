import { useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

export interface TransferItem {
  id: string
  label: string
}

interface TransferListProps {
  items: TransferItem[]
  value: string[]
  onChange: (ids: string[]) => void
  searchPlaceholder?: string
  emptyHint?: string
}

/** 可过滤的穿梭器：左侧全量列表（带搜索+全选），右侧已选列表（带清除+单项移除）。
 * v1 自研（shadcn 没有对应组件），供 skills/MCP 绑定复用。 */
export function TransferList({
  items,
  value,
  onChange,
  searchPlaceholder = '请输入',
  emptyHint = '暂无可选项',
}: TransferListProps) {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return items
    return items.filter((item) => item.label.toLowerCase().includes(q))
  }, [items, query])

  const selectedItems = useMemo(
    () => items.filter((item) => value.includes(item.id)),
    [items, value]
  )

  const allFilteredSelected = filtered.length > 0 && filtered.every((item) => value.includes(item.id))

  function toggleItem(id: string, checked: boolean) {
    onChange(checked ? [...value, id] : value.filter((v) => v !== id))
  }

  function toggleSelectAllFiltered(checked: boolean) {
    const filteredIds = new Set(filtered.map((item) => item.id))
    if (checked) {
      onChange([...value, ...filtered.filter((item) => !value.includes(item.id)).map((item) => item.id)])
    } else {
      onChange(value.filter((v) => !filteredIds.has(v)))
    }
  }

  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyHint}</p>
  }

  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="flex flex-col gap-2 rounded-lg border">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={allFilteredSelected} onCheckedChange={(c) => toggleSelectAllFiltered(c === true)} />
            全选
          </label>
          <span className="text-xs text-muted-foreground">共 {filtered.length} 项</span>
        </div>
        <div className="px-3">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={searchPlaceholder}
            className="text-sm"
          />
        </div>
        <div className="flex max-h-56 flex-col gap-0.5 overflow-y-auto px-3 pb-3">
          {filtered.length === 0 && <p className="py-2 text-sm text-muted-foreground">没有匹配项</p>}
          {filtered.map((item) => (
            <label
              key={item.id}
              className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-muted"
            >
              <Checkbox
                checked={value.includes(item.id)}
                onCheckedChange={(c) => toggleItem(item.id, c === true)}
              />
              {item.label}
            </label>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2 rounded-lg border">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <button
            type="button"
            className={cn(
              'text-sm text-muted-foreground hover:text-foreground',
              value.length === 0 && 'pointer-events-none opacity-50'
            )}
            onClick={() => onChange([])}
          >
            清除
          </button>
          <span className="text-xs text-muted-foreground">已选 {value.length} 项</span>
        </div>
        <div className="flex max-h-64 flex-col gap-0.5 overflow-y-auto px-3 pb-3">
          {selectedItems.length === 0 && <p className="py-2 text-sm text-muted-foreground">还没有选择项目</p>}
          {selectedItems.map((item) => (
            <div
              key={item.id}
              className="group flex items-center justify-between gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-muted"
            >
              {item.label}
              <button
                type="button"
                aria-label="移除"
                className="text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-foreground"
                onClick={() => toggleItem(item.id, false)}
              >
                <X className="size-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
