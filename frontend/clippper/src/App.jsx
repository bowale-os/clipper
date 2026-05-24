import ClerkProviderWithRoutes from './services/auth/ClerkProviderWithRoutes'
import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import DashBoard from './pages/DashBoard'
import SsoCallback from './services/auth/SsoCallback'
import './App.css'

function App() {
  return (
    <ClerkProviderWithRoutes>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/sso-callback" element={<SsoCallback />} />
        <Route path="/sign-in" element={<SsoCallback />} />
        <Route path="/sign-up" element={<SsoCallback />} />
        <Route path="/dashboard" element={<DashBoard />} />
      </Routes>
    </ClerkProviderWithRoutes>
  )
}

export default App
