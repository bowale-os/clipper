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

  const runWithToken = useCallback(
    async (callback) => {
      try {
        let token

        try {
          token = await getToken()
        } catch {
          throw new AuthExpiredError()
        }

        if (!token) {
          throw new AuthExpiredError()
        }

        return await callback(token)
      } catch (error) {
        if (error instanceof AuthExpiredError) {
          await handleExpiredAuth()
        }

        throw error
      }
    },
    [getToken, handleExpiredAuth],
  )

  return { runWithToken }
}
