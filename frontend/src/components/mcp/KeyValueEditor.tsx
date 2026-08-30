import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { KeyValuePair } from '@/lib/keyValuePairs'

interface KeyValueEditorProps {
  pairs: KeyValuePair[]
  onChange: (pairs: KeyValuePair[]) => void
  addLabel: string
  keyPlaceholder?: string
  valuePlaceholder?: string
}

/** env/headers 通用的 key-value 编辑器；value 由后端脱敏时会是固定占位符 "********"，
 * 这里原样当普通文本展示——用户不碰这一行就原样提交占位符，后端会自动保留旧值（见 T1.4 决策记录）。 */
export function KeyValueEditor({
  pairs,
  onChange,
  addLabel,
  keyPlaceholder = 'KEY',
  valuePlaceholder = 'value',
}: KeyValueEditorProps) {
  function updateRow(index: number, patch: Partial<KeyValuePair>) {
    onChange(pairs.map((pair, i) => (i === index ? { ...pair, ...patch } : pair)))
  }

  function removeRow(index: number) {
    onChange(pairs.filter((_, i) => i !== index))
  }

  return (
    <div className="flex flex-col gap-2">
      {pairs.map((pair, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input
            value={pair.key}
            onChange={(e) => updateRow(index, { key: e.target.value })}
            placeholder={keyPlaceholder}
            className="flex-1 font-mono text-sm"
          />
          <Input
            value={pair.value}
            onChange={(e) => updateRow(index, { value: e.target.value })}
            placeholder={valuePlaceholder}
            className="flex-1 font-mono text-sm"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="删除"
            onClick={() => removeRow(index)}
          >
            <X className="size-3.5" />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => onChange([...pairs, { key: '', value: '' }])}
      >
        {addLabel}
      </Button>
    </div>
  )
}
