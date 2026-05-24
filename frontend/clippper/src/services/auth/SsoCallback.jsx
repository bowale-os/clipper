import { AuthenticateWithRedirectCallback } from '@clerk/react'
import { Navigate } from 'react-router-dom'

function SsoCallback() {
  const isHashCallback = window.location.hash.startsWith('#/sso-callback')
  const isPathCallback = window.location.pathname === '/sso-callback'

  if (!isHashCallback && !isPathCallback) {
    return <Navigate to="/" replace />
  }

  return <AuthenticateWithRedirectCallback />
}

export default SsoCallback
