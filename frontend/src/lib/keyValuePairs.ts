export interface KeyValuePair {
  key: string
  value: string
}

export function pairsToRecord(pairs: KeyValuePair[]): Record<string, string> {
  const record: Record<string, string> = {}
  for (const { key, value } of pairs) {
    if (key.trim()) record[key.trim()] = value
  }
  return record
}

export function recordToPairs(record: Record<string, string>): KeyValuePair[] {
  return Object.entries(record).map(([key, value]) => ({ key, value }))
}
