import { Routes, Route } from 'react-router-dom'
import { useAuth, SignIn, SignUp } from '@clerk/react'
import ClerkProviderWithRoutes from './services/auth/ClerkProviderWithRoutes'
import ProtectedRoute from './services/auth/ProtectedRoute'
import SsoCallback from './services/auth/SsoCallback'
import Landing from './pages/Landing'
import Studio from './pages/Studio'
import Settings from './pages/Settings'
import Trim from './pages/Trim'
import NotFound from './pages/NotFound'
import './App.css'

/**
 * One address for the app itself. Signed out it sells; signed in it is the tool.
 * Nothing else needs a name.
 */
function Root() {
  const { isLoaded, isSignedIn } = useAuth()

  if (!isLoaded) {
    return null
  }

  return isSignedIn ? <Studio /> : <Landing />
}

function App() {
  return (
    <ClerkProviderWithRoutes>
      <Routes>
        <Route path="/" element={<Root />} />
        <Route path="/sso-callback" element={<SsoCallback />} />
        <Route
          path="/sign-in/*"
          element={
            <main className="auth-page">
              <SignIn routing="path" path="/sign-in" />
            </main>
          }
        />
        <Route
          path="/sign-up/*"
          element={
            <main className="auth-page">
              <SignUp routing="path" path="/sign-up" />
            </main>
          }
        />
        <Route
          path="/settings"
          element={
            <ProtectedRoute>
              <Settings />
            </ProtectedRoute>
          }
        />
        <Route
          path="/trim/:videoId"
          element={
            <ProtectedRoute>
              <Trim />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </ClerkProviderWithRoutes>
  )
}

export default App
