import { useCallback, useEffect, useState } from 'react'
import { ApiError, getUserVideos } from '../services/api'
import { useAuthedApi } from './useAuthedApi'

const initialState = {
  data: null,
  error: '',
  isLoading: true,
}

function getReadableError(error) {
  if (error instanceof ApiError) {
    return error.status ? `${error.message} (${error.status})` : error.message
  }

  if (error instanceof Error) {
    return error.message
  }

  return 'Videos could not be loaded.'
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
        error: getReadableError(error),
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
