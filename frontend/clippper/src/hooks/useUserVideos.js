import { useCallback, useEffect, useState } from 'react'
import { getUserVideos } from '../services/api'
import { useAuthedApi } from './useAuthedApi'
import { getReadableError } from '../lib/errors'

const initialState = {
  data: null,
  error: '',
  isLoading: true,
}

export function useUserVideos() {
  const { runWithToken } = useAuthedApi()
  const [state, setState] = useState(initialState)

  const loadVideos = useCallback(async ({ markLoading = true } = {}) => {
    try {
      if (markLoading) {
        setState((current) => ({
          ...current,
          error: '',
          isLoading: true,
        }))
      }

      const data = await runWithToken((token) => getUserVideos({ token }))

      setState({
        data,
        error: '',
        isLoading: false,
      })
    } catch (error) {
      setState({
        data: null,
        error: getReadableError(error, 'Videos could not be loaded.'),
        isLoading: false,
      })
    }
  }, [runWithToken])

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      loadVideos({ markLoading: false })
    }, 0)

    return () => window.clearTimeout(timeoutId)
  }, [loadVideos])

  return {
    ...state,
    refresh: loadVideos,
  }
}
