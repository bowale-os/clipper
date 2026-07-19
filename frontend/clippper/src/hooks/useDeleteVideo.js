import { useCallback, useState } from 'react'
import { deleteVideo } from '../services/api'
import { useAuthedApi } from './useAuthedApi'
import { getReadableError } from '../lib/errors'

/**
 * Deleting takes two steps on purpose. The server drops the stored file and
 * every clip and moment that came off it, and none of that comes back, so
 * `ask` only arms the row and `confirm` is what actually deletes. `cancel`
 * stays available the whole time.
 */
export function useDeleteVideo({ onDeleted } = {}) {
  const { runWithToken } = useAuthedApi()
  const [pendingId, setPendingId] = useState('')
  const [deletingId, setDeletingId] = useState('')
  const [error, setError] = useState('')

  const ask = useCallback((videoId) => {
    setError('')
    setPendingId(videoId)
  }, [])

  const cancel = useCallback(() => {
    setError('')
    setPendingId('')
  }, [])

  const confirm = useCallback(
    async (videoId) => {
      setError('')
      setDeletingId(videoId)

      try {
        await runWithToken((token) => deleteVideo({ videoId, token }))
        setPendingId('')
        onDeleted?.(videoId)
      } catch (caught) {
        // Leave the row armed so the confirm button is still there to retry.
        setError(getReadableError(caught, 'That stream could not be deleted.'))
      } finally {
        setDeletingId('')
      }
    },
    [onDeleted, runWithToken],
  )

  return { ask, cancel, confirm, deletingId, error, pendingId }
}
