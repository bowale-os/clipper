import { ClerkProvider } from '@clerk/react'
import { BrowserRouter, useNavigate } from 'react-router-dom'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

if (!PUBLISHABLE_KEY) {
  throw new Error('Clerk publishable key is missing.')
}

// Mirrors src/styles/tokens.css so Clerk's modals sit on the same cream paper as
// the rest of the app. There is only one theme, so there is only one of these.
const appearance = {
  variables: {
    colorPrimary: '#e01c74',
    colorText: '#0d0d0d',
    colorTextSecondary: '#57534b',
    colorBackground: '#ffedd2',
    colorInputBackground: '#ffffff',
    colorInputText: '#0d0d0d',
    colorDanger: '#c02626',
    borderRadius: '8px',
    fontFamily: "'Poppins', 'Nunito Sans', 'Segoe UI', system-ui, sans-serif",
  },
  elements: {
    modalBackdrop: {
      backgroundColor: 'rgba(13, 13, 13, 0.5)',
    },
    card: {
      border: '1px solid #e4d3b6',
      boxShadow: 'none',
    },
    formButtonPrimary: {
      minHeight: '2.75rem',
      fontSize: '0.9375rem',
      fontWeight: 600,
      boxShadow: 'none',
    },
    formFieldInput: {
      minHeight: '2.75rem',
      border: '1px solid #e4d3b6',
    },
  },
}

// Clerk steps through sign-in by navigating (password, email code, factor two).
// Those hops have to go through the router, not the browser, or every step
// reloads the page and takes the half-finished sign-in with it. useNavigate only
// exists under a Router, which is why the Router is on the outside here.
function ClerkWithRouter({ children }) {
  const navigate = useNavigate()

  return (
    <ClerkProvider
      publishableKey={PUBLISHABLE_KEY}
      appearance={appearance}
      signInForceRedirectUrl="/"
      signUpForceRedirectUrl="/"
      signInFallbackRedirectUrl="/"
      signUpFallbackRedirectUrl="/"
      signInUrl="/sign-in"
      signUpUrl="/sign-up"
      routerPush={(to) => navigate(to)}
      routerReplace={(to) => navigate(to, { replace: true })}
    >
      {children}
    </ClerkProvider>
  )
}

export default function ClerkProviderWithRoutes({ children }) {
  return (
    <BrowserRouter>
      <ClerkWithRouter>{children}</ClerkWithRouter>
    </BrowserRouter>
  )
}
