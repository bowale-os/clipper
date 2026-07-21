import { useEffect, useState } from 'react'
import { getClip } from '../services/api'
import { useAuthedApi } from './useAuthedApi'
import { getReadableError } from '../lib/errors'

const POLL_INTERVAL_MS = 3000
const POLL_TIMEOUT_MS = 10 * 60 * 1000

const idleState = { status: 'idle', url: null, error: '' }

/**
 * Rendering happens on a worker, so POST /clips/create only hands back a
 * clip_id. This polls GET /clips/{id} until the render lands, and stops on
 * ready, error, timeout, or unmount.
 */
export function useClipStatus(clipId) {
  const { runWithToken } = useAuthedApi()
  const [state, setState] = useState(() => (clipId ? { ...idleState, status: 'queued' } : idleState))

  useEffect(() => {
    let cancelled = false
    let timeoutId
    const startedAt = Date.now()

    async function poll() {
      try {
        const data = await runWithToken((token) => getClip({ clipId, token }))

        if (cancelled) {
          return
        }

        if (data?.status === 'ready') {
          setState(
            data.url
              ? { status: 'ready', url: data.url, error: '' }
              : { status: 'error', url: null, error: 'The clip rendered, but its download link is missing.' },
          )
          return
        }

        if (data?.status === 'error') {
          setState({
            status: 'error',
            url: null,
            error: 'Rendering failed for this clip. Try generating it again.',
          })
          return
        }

        setState({ status: data?.status || 'queued', url: null, error: '' })

        if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
          setState({
            status: 'error',
            url: null,
            error: 'This is taking longer than expected. Check the clip again in a few minutes.',
          })
          return
        }

        timeoutId = window.setTimeout(poll, POLL_INTERVAL_MS)
      } catch (error) {
        if (!cancelled) {
          setState({ status: 'error', url: null, error: getReadableError(error, 'The clip status could not be checked.') })
        }
      }
    }

    // Deferred a tick: setting state straight from an effect body triggers a
    // cascading render (react-hooks/set-state-in-effect).
    timeoutId = window.setTimeout(clipId ? poll : () => setState(idleState), 0)

    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
    }
  }, [clipId, runWithToken])

  return state
}
