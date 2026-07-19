import { useCallback, useEffect, useState } from 'react'
import { listClips } from '../services/api'
import { useAuthedApi } from './useAuthedApi'
import { getReadableError } from '../lib/errors'

/**
 * The clips already on record for a video. Detect renders the strongest few on
 * its own, so by the time this screen opens some of them are finished and
 * sitting in storage. Without this the grid would never learn they exist and
 * would queue the same cut a second time the moment someone tapped it.
 *
 * Only fetches. Anything still queued or rendering gets handed to
 * useClipRenders, which already owns the polling for the whole screen.
 */
export function useVideoClips(videoId) {
  const { runWithToken } = useAuthedApi()
  const [state, setState] = useState({ clips: [], error: '', isLoading: Boolean(videoId) })

  const load = useCallback(async () => {
    if (!videoId) {
      setState({ clips: [], error: '', isLoading: false })
      return
    }

    try {
      const data = await runWithToken((token) => listClips({ token, videoId }))
      setState({ clips: Array.isArray(data?.clips) ? data.clips : [], error: '', isLoading: false })
    } catch (error) {
      // A failure here is not worth an error on screen: the moments still render
      // and every tile still works, they just start from scratch.
      setState({
        clips: [],
        error: getReadableError(error, 'Your finished clips could not be loaded.'),
        isLoading: false,
      })
    }
  }, [runWithToken, videoId])

  useEffect(() => {
    // Deferred a tick so the load doesn't set state from the effect body.
    const timeoutId = window.setTimeout(load, 0)
    return () => window.clearTimeout(timeoutId)
  }, [load])

  return { ...state, refresh: load }
}
