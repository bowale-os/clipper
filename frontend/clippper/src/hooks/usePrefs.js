import { useCallback, useEffect, useState } from 'react'
import { CLIP_FORMATS, DEFAULT_CLIP_FORMAT } from '../services/api'

const STORAGE_KEY = 'clippper-prefs'

const defaults = {
  format: DEFAULT_CLIP_FORMAT,
  captions: true,
}

function read() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const saved = raw ? JSON.parse(raw) : null

    if (!saved || typeof saved !== 'object') {
      return defaults
    }

    return {
      format: CLIP_FORMATS.includes(saved.format) ? saved.format : defaults.format,
      captions: typeof saved.captions === 'boolean' ? saved.captions : defaults.captions,
    }
  } catch {
    // Private mode or blocked storage: the defaults still work for this session.
    return defaults
  }
}

/**
 * What most of your clips come out as. These are the defaults every render
 * starts from, so the preview never has to ask before it can hand you a file.
 * Settings writes them; every screen reads them.
 */
export function usePrefs() {
  const [prefs, setPrefs] = useState(read)

  // Keep other tabs in step, so changing a default in one doesn't surprise you
  // in the other.
  useEffect(() => {
    function handleStorage(event) {
      if (event.key === STORAGE_KEY) {
        setPrefs(read())
      }
    }

    window.addEventListener('storage', handleStorage)
    return () => window.removeEventListener('storage', handleStorage)
  }, [])

  const update = useCallback((changes) => {
    setPrefs((current) => {
      const next = { ...current, ...changes }

      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      } catch {
        // Storage is blocked; the change still applies for this session.
      }

      return next
    })
  }, [])

  return { prefs, update }
}
