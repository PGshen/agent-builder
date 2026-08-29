import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { getHealth, type HealthResponse } from '../lib/apiClient'

type State =
  | { phase: 'checking' }
  | { phase: 'unreachable' }
  | { phase: 'done'; status: HealthResponse['status'] }

export function BackendStatus() {
  const [state, setState] = useState<State>({ phase: 'checking' })

  useEffect(() => {
    let cancelled = false

    getHealth()
      .then((result) => {
        if (cancelled) return
        if (!result.data) {
          setState({ phase: 'unreachable' })
          return
        }
        setState({ phase: 'done', status: result.data.status })
      })
      .catch(() => {
        if (!cancelled) setState({ phase: 'unreachable' })
      })

    return () => {
      cancelled = true
    }
  }, [])

  const label =
    state.phase === 'checking'
      ? 'Backend: checking…'
      : state.phase === 'unreachable'
        ? 'Backend: unreachable'
        : `Backend: ${state.status}`

  const variant =
    state.phase === 'done' && state.status === 'ok'
      ? 'default'
      : state.phase === 'checking'
        ? 'secondary'
        : 'destructive'

  return (
    <Badge variant={variant} className="font-mono" data-testid="backend-status">
      {label}
    </Badge>
  )
}
