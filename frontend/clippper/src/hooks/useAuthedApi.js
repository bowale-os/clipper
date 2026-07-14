import { useCallback } from 'react'
import { useAuth } from '@clerk/react'
import { useNavigate } from 'react-router-dom'
import { AuthExpiredError } from '../services/api'

export function useAuthedApi() {
  const { getToken, signOut } = useAuth()
  const navigate = useNavigate()

  const handleExpiredAuth = useCallback(async () => {
    try {
      await signOut()
    } finally {
      navigate('/', { replace: true })
    }
  }, [navigate, signOut])

  // Fetches a fresh Clerk token; used per-request by long-running uploads
  // because a single token expires (~60s) before a large upload finishes.
  const getFreshToken = useCallback(async () => {
    let token

    try {
      token = await getToken()
    } catch {
      throw new AuthExpiredError()
    }

    if (!token) {
      throw new AuthExpiredError()
    }

    return token
  }, [getToken])

  const runWithToken = useCallback(
    async (callback) => {
      try {
        const token = await getFreshToken()
        return await callback(token)
      } catch (error) {
        if (error instanceof AuthExpiredError) {
          await handleExpiredAuth()
        }

        throw error
      }
    },
    [getFreshToken, handleExpiredAuth],
  )

  return { runWithToken, getFreshToken, handleExpiredAuth }
}
