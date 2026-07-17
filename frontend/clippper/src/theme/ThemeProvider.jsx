import { useCallback, useMemo, useState } from 'react'
import { STORAGE_KEY, ThemeContext } from './themeContext'

function readInitialTheme() {
  // index.html already resolved this before paint; read it back so the first
  // render matches the DOM instead of fighting it.
  if (typeof document === 'undefined') {
    return 'dark'
  }

  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(readInitialTheme)

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next = current === 'dark' ? 'light' : 'dark'
      document.documentElement.dataset.theme = next

      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
        // Private mode or blocked storage: the theme still applies for this session.
      }

      return next
    })
  }, [])

  const value = useMemo(() => ({ theme, toggleTheme }), [theme, toggleTheme])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
