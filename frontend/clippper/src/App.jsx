import ClerkProviderWithRoutes from './services/auth/ClerkProviderWithRoutes'
import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import DashBoard from './pages/DashBoard'
import Videos from './pages/Videos'
import ClipEditor from './pages/ClipEditor'
import Moments from './pages/Moments'
import SsoCallback from './services/auth/SsoCallback'
import ProtectedRoute from './services/auth/ProtectedRoute'
import MomentClipViewer from './pages/MomentClipViewer'
import { ThemeProvider } from './theme/ThemeProvider'
import './App.css'

function App() {
  return (
    <ThemeProvider>
      <ClerkProviderWithRoutes>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/sso-callback" element={<SsoCallback />} />
          <Route path="/sign-in" element={<SsoCallback />} />
          <Route path="/sign-up" element={<SsoCallback />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <DashBoard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/videos"
            element={
              <ProtectedRoute>
                <Videos />
              </ProtectedRoute>
            }
          />
          <Route
            path="/videos/:videoId/moments"
            element={
              <ProtectedRoute>
                <Moments />
              </ProtectedRoute>
            }
          />
          <Route
            path="/videos/:videoId/clips"
            element={
              <ProtectedRoute>
                <ClipEditor />
              </ProtectedRoute>
            }
          />
          <Route
            path="/videos/:videoId/moments/:momentIndex/clip"
            element={
              <ProtectedRoute>
                <MomentClipViewer />
              </ProtectedRoute>
            }
          />
        </Routes>
      </ClerkProviderWithRoutes>
    </ThemeProvider>
  )
}

export default App
