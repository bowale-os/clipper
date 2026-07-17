import { ClerkProvider } from '@clerk/react'
import { BrowserRouter } from 'react-router-dom'
import { useTheme } from '../../theme/themeContext'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

if (!PUBLISHABLE_KEY) {
  throw new Error('Clerk publishable key is missing.')
}

// Mirrors the semantic tokens in src/styles/tokens.css so Clerk's modals sit in
// the same theme as the rest of the app.
const themeVariables = {
  dark: {
    colorPrimary: '#7c5cff',
    colorText: '#d5d2df',
    colorTextSecondary: '#8b8799',
    colorBackground: '#17151f',
    colorInputBackground: '#211e2c',
    colorInputText: '#f6f5fa',
  },
  light: {
    colorPrimary: '#592eff',
    colorText: '#353241',
    colorTextSecondary: '#5f5f69',
    colorBackground: '#ffffff',
    colorInputBackground: '#ffffff',
    colorInputText: '#21164c',
  },
}

function buildAppearance(theme) {
  return {
    variables: {
      ...themeVariables[theme],
      borderRadius: '12px',
      fontFamily: "'Plus Jakarta Sans', ui-sans-serif, system-ui, sans-serif",
    },
    elements: {
      modalBackdrop: {
        backgroundColor: theme === 'dark' ? 'rgba(6, 5, 10, 0.72)' : 'rgba(33, 22, 76, 0.32)',
      },
      modalContent: {
        width: 'min(96vw, 760px)',
        maxWidth: '760px',
      },
      cardBox: {
        width: '100%',
        maxWidth: '760px',
      },
      card: {
        width: '100%',
        padding: '3rem',
      },
      headerTitle: {
        fontSize: '2rem',
      },
      headerSubtitle: {
        fontSize: '1rem',
      },
      formFieldInput: {
        minHeight: '3rem',
        fontSize: '1rem',
      },
      formButtonPrimary: {
        minHeight: '3rem',
        fontSize: '1rem',
      },
    },
  }
}

export default function ClerkProviderWithRoutes({ children }) {
  const { theme } = useTheme()

  return (
    <ClerkProvider
      publishableKey={PUBLISHABLE_KEY}
      appearance={buildAppearance(theme)}
      signInForceRedirectUrl="/dashboard"
      signUpForceRedirectUrl="/dashboard"
      signInFallbackRedirectUrl="/dashboard"
      signUpFallbackRedirectUrl="/dashboard"
      signInUrl="/sign-in"
      signUpUrl="/sign-up"
      // Important: Add this for better React Router integration
      routerPush={(to) => (window.location.href = to)}
      routerReplace={(to) => window.location.replace(to)}
    >
      <BrowserRouter>{children}</BrowserRouter>
    </ClerkProvider>
  )
}
