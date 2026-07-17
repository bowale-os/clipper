import { createContext, useContext } from 'react'

export const STORAGE_KEY = 'clippper-theme'

export const ThemeContext = createContext({ theme: 'dark', toggleTheme: () => {} })

export function useTheme() {
  return useContext(ThemeContext)
}
