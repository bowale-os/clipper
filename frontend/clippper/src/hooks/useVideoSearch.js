import { useEffect, useRef, useState } from 'react'
import { searchVideos } from '../services/api'
import { useAuthedApi } from './useAuthedApi'

const DEBOUNCE_MS = 220

// A plain filename contains match, used when the server search errors so the box
// still narrows something rather than going dead.
function clientFilter(videos, query) {
  const needle = query.trim().toLowerCase()
  return videos.filter((video) => (video?.filename || '').toLowerCase().includes(needle))
}

/**
 * Debounced name search over the user's videos. Hits GET /videos/search (hybrid
 * semantic + lexical on the backend) and falls back to a local filename filter
 * if that request fails. Empty query parks the hook and returns nothing.
 */
export function useVideoSearch(query, fallbackVideos = []) {
  const { runWithToken } = useAuthedApi()
  const [results, setResults] = useState([])
  const [isSearching, setIsSearching] = useState(false)

  // Kept in a ref so a changing list (the 15s poll) doesn't retrigger the search.
  const fallbackRef = useRef(fallbackVideos)
  useEffect(() => {
    fallbackRef.current = fallbackVideos
  }, [fallbackVideos])
  const requestId = useRef(0)

  const trimmed = query.trim()

  useEffect(() => {
    const q = query.trim()

    if (!q) {
      return
    }

    const id = ++requestId.current

    // All state changes happen inside the debounced callback, never synchronously
    // in the effect body, so an empty query simply parks with no work queued.
    const timeoutId = window.setTimeout(async () => {
      setIsSearching(true)
      try {
        const data = await runWithToken((token) => searchVideos({ q, token }))
        if (id !== requestId.current) {
          return
        }
        setResults(Array.isArray(data?.videos) ? data.videos : [])
      } catch {
        if (id !== requestId.current) {
          return
        }
        setResults(clientFilter(fallbackRef.current, q))
      } finally {
        if (id === requestId.current) {
          setIsSearching(false)
        }
      }
    }, DEBOUNCE_MS)

    return () => window.clearTimeout(timeoutId)
  }, [query, runWithToken])

  // Empty query shows nothing without needing to clear state in an effect.
  return {
    results: trimmed ? results : [],
    isSearching: trimmed ? isSearching : false,
  }
}
