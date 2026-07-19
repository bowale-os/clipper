import { useCallback, useEffect, useState } from 'react'
import { ApiError, listClips } from '../services/api'
import { useAuthedApi } from './useAuthedApi'
import { getReadableError } from '../lib/errors'

const POLL_INTERVAL_MS = 3000

// A clip left stuck on "rendering" by a worker that died would otherwise keep this
// timer alive for as long as the tab is open. Matches the per-render ceiling in
// useClipRenders, so both give up on the same clip at the same time.
const POLL_CEILING_MS = 10 * 60 * 1000

const PENDING_CLIP = ['queued', 'rendering', 'processing']
const SETTLED_VIDEO = ['ready', 'error']

/**
 * Whether the clip list can still change on its own.
 *
 * Two things have to be true. The video has to be finished, because detect is the
 * only thing that adds clips without anyone asking, and it has already run by the
 * time a video reaches ready. And no clip can still be queued or rendering, since
 * those are the two states a worker moves out from under us. "error" counts as
 * finished on both sides: that work died, so nothing more is coming from it.
 */
function isSettled(data) {
  const clips = Array.isArray(data?.clips) ? data.clips : []

  return (
    SETTLED_VIDEO.includes(data?.video_status) &&
    !clips.some((clip) => PENDING_CLIP.includes(clip.status))
  )
}

/**
 * The clips on record for a video, kept fresh while any of them are still being made.
 *
 * Detect renders the strongest few on its own, so opening this screen mid-pipeline
 * shows some clips finished, some queued, and more landing over the next minute. A
 * single fetch on mount caught only the ones that happened to exist at that instant,
 * and the rest never appeared until a reload.
 *
 * So it polls, and then it stops. Once the video is finished and no clip is pending,
 * the list cannot change without the user clicking something, and re-fetching an
 * identical response every three seconds for the rest of the session buys nothing.
 * Renders the user starts are not this hook's problem: useClipRenders owns those and
 * seeds itself from what comes back here.
 */
export function useVideoClips(videoId) {
  const { runWithToken } = useAuthedApi()
  const [state, setState] = useState({
    clips: [],
    videoStatus: '',
    error: '',
    isLoading: Boolean(videoId),
  })

  /** Fetches once. Returns what the poller should do next. */
  const load = useCallback(async () => {
    if (!videoId) {
      setState({ clips: [], videoStatus: '', error: '', isLoading: false })
      return 'stop'
    }

    try {
      const data = await runWithToken((token) => listClips({ token, videoId }))

      setState({
        clips: Array.isArray(data?.clips) ? data.clips : [],
        videoStatus: data?.video_status || '',
        error: '',
        isLoading: false,
      })

      return isSettled(data) ? 'settled' : 'pending'
    } catch (error) {
      // The video was deleted, here or in another tab. Nothing left to poll for, and
      // asking again would 404 just as fast.
      if (error instanceof ApiError && error.status === 404) {
        setState({ clips: [], videoStatus: '', error: '', isLoading: false })
        return 'stop'
      }

      // Anything else is probably a blip. Keep the clips already on screen rather
      // than blanking the grid over one failed request, and let the poll try again.
      setState((current) => ({
        ...current,
        error: getReadableError(error, 'Your finished clips could not be loaded.'),
        isLoading: false,
      }))

      return 'pending'
    }
  }, [runWithToken, videoId])

  useEffect(() => {
    let cancelled = false
    let timeoutId
    let settledReads = 0
    let deadline = Date.now() + POLL_CEILING_MS

    function schedule(delay) {
      window.clearTimeout(timeoutId)
      timeoutId = window.setTimeout(tick, delay)
    }

    async function tick() {
      // Nobody is looking. Stop scheduling rather than polling into a background
      // tab; the visibility listener picks the loop back up.
      if (cancelled || document.hidden) {
        return
      }

      const outcome = await load()

      if (cancelled || outcome === 'stop') {
        return
      }

      // One confirming read after the list first looks final, so a clip committed in
      // the same moment the video flipped to ready is not missed by a hair.
      settledReads = outcome === 'settled' ? settledReads + 1 : 0

      if (settledReads > 1 || Date.now() > deadline) {
        return
      }

      schedule(POLL_INTERVAL_MS)
    }

    function handleVisibility() {
      if (cancelled || document.hidden) {
        return
      }

      // Coming back to the tab is a request for fresh data, and it earns a fresh
      // ceiling too: someone is watching again, so it is worth another look even if
      // the loop had settled or given up while they were away.
      settledReads = 0
      deadline = Date.now() + POLL_CEILING_MS
      schedule(0)
    }

    document.addEventListener('visibilitychange', handleVisibility)
    // Deferred a tick so the first load doesn't set state from the effect body.
    schedule(0)

    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [load])

  return { ...state, refresh: load }
}
