import { useCallback, useEffect, useState } from 'react'
import { getVideoMoments } from '../services/api'
import { useAuthedApi } from './useAuthedApi'
import { getReadableError } from '../lib/errors'

function getFinalScore(moment) {
  const value = Number(moment?.scores?.final)
  return Number.isFinite(value) ? value : 0
}

/**
 * Moments for one video, best first — that ordering is the whole point of the
 * grid. Passing a falsy videoId parks the hook rather than firing a request.
 */
export function useVideoMoments(videoId) {
  const { runWithToken } = useAuthedApi()
  const [state, setState] = useState({ data: null, error: '', isLoading: Boolean(videoId) })

  const load = useCallback(async () => {
    if (!videoId) {
      setState({ data: null, error: '', isLoading: false })
      return
    }

    try {
      setState((current) => ({ ...current, error: '', isLoading: true }))
      const data = await runWithToken((token) => getVideoMoments({ token, videoId }))

      const moments = Array.isArray(data?.moments)
        ? [...data.moments].sort((a, b) => getFinalScore(b) - getFinalScore(a))
        : []

      setState({ data: { ...data, moments }, error: '', isLoading: false })
    } catch (error) {
      setState({
        data: null,
        error: getReadableError(error, 'Those clips could not be loaded.'),
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
