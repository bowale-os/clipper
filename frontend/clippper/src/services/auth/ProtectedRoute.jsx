import { RedirectToSignIn, useAuth } from '@clerk/react'

function ProtectedRoute({ children }) {
  const { isLoaded, isSignedIn } = useAuth()

  if (!isLoaded) {
    return null
  }

  if (!isSignedIn) {
    return <RedirectToSignIn forceRedirectUrl="/dashboard" />
  }

  return children
}

export default ProtectedRoute
