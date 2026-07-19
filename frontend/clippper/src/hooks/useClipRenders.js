import { useCallback, useEffect, useRef, useState } from 'react'
import { createClip, getClip } from '../services/api'
import { useAuthedApi } from './useAuthedApi'
import { getReadableError } from '../lib/errors'

const POLL_INTERVAL_MS = 3000
const POLL_TIMEOUT_MS = 10 * 60 * 1000

const PENDING = ['queued', 'rendering', 'processing']

export function getMomentKey(moment, videoId) {
  return moment?.id || `${videoId}:${moment?.start_sec}-${moment?.end_sec}`
}

function triggerDownload(url, filename) {
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

function toFilename(moment) {
  const base = String(moment?.title || 'clip')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')

  return `${base || 'clip'}.mp4`
}

/**
 * Renders are queued on a worker, so creating one only hands back an id. This
 * owns every in-flight render for the screen and polls them together, so a
 * dozen clips can be rendering at once without each tile running its own timer.
 */
export function useClipRenders() {
  const { runWithToken } = useAuthedApi()
  const [renders, setRenders] = useState({})
  // The poller and the click handlers read this so they don't have to
  // re-subscribe every time a status changes. Synced on commit, so it always
  // holds the last rendered value by the time anything reads it.
  const rendersRef = useRef(renders)

  useEffect(() => {
    rendersRef.current = renders
  }, [renders])

  const patch = useCallback((key, changes) => {
    setRenders((current) => ({ ...current, [key]: { ...current[key], ...changes } }))
  }, [])

  const start = useCallback(
    async ({ captions, format, moment, videoId, autoDownload = false }) => {
      const key = getMomentKey(moment, videoId)
      const existing = rendersRef.current[key]

      // Already have this exact cut? Reuse it rather than paying to render twice.
      if (existing && existing.format === format && existing.captions === captions) {
        if (existing.status === 'ready' && existing.url) {
          if (autoDownload) {
            triggerDownload(existing.url, toFilename(moment))
          }
          return
        }

        if (PENDING.includes(existing.status)) {
          if (autoDownload) {
            patch(key, { autoDownload: true })
          }
          return
        }
      }

      patch(key, {
        autoDownload,
        captions,
        clipId: null,
        error: '',
        format,
        local: true,
        moment,
        startedAt: Date.now(),
        status: 'queued',
        url: null,
      })

      try {
        const clip = await runWithToken((token) =>
          createClip({
            videoId,
            startSec: Number(moment.start_sec),
            endSec: Number(moment.end_sec),
            format,
            captions,
            momentId: moment.id,
            token,
          }),
        )

        patch(key, { clipId: clip.clip_id })
      } catch (error) {
        patch(key, {
          status: 'error',
          error: getReadableError(error, 'The clip could not be queued.'),
        })
      }
    },
    [patch, runWithToken],
  )

  /**
   * Adopt clips the server already knows about, so they read as ready or working
   * without anyone clicking. Entries are shaped exactly like the ones start()
   * makes, which means the poller below picks up the unfinished ones for free.
   *
   * A render started in this session always wins: the user asked for that one
   * after the list was fetched, so it is the newer intent.
   */
  const seed = useCallback((entries) => {
    setRenders((current) => {
      const next = { ...current }
      let changed = false

      for (const entry of entries) {
        const existing = next[entry.key]

        if (existing?.local) {
          continue
        }

        // Re-seeding an unchanged entry would reset startedAt and keep the
        // render alive past its timeout, so only write real changes.
        if (existing && existing.status === entry.status && existing.url === entry.url) {
          continue
        }

        next[entry.key] = {
          autoDownload: false,
          captions: entry.captions,
          clipId: entry.clipId,
          error: '',
          format: entry.format,
          local: false,
          moment: entry.moment,
          startedAt: Date.now(),
          status: entry.status,
          url: entry.url,
        }
        changed = true
      }

      return changed ? next : current
    })
  }, [])

  const clear = useCallback((key) => {
    setRenders((current) => {
      const next = { ...current }
      delete next[key]
      return next
    })
  }, [])

  // One timer for every pending render on the screen.
  useEffect(() => {
    let cancelled = false

    async function poll() {
      const entries = Object.entries(rendersRef.current).filter(
        ([, render]) => render.clipId && PENDING.includes(render.status),
      )

      await Promise.all(
        entries.map(async ([key, render]) => {
          if (Date.now() - render.startedAt > POLL_TIMEOUT_MS) {
            patch(key, {
              status: 'error',
              error: 'This is taking longer than expected. Try it again in a few minutes.',
            })
            return
          }

          try {
            const data = await runWithToken((token) => getClip({ clipId: render.clipId, token }))

            if (cancelled) {
              return
            }

            if (data?.status === 'ready') {
              if (!data.url) {
                patch(key, {
                  status: 'error',
                  error: 'The clip rendered, but its download link is missing.',
                })
                return
              }

              patch(key, { status: 'ready', url: data.url, error: '' })

              if (render.autoDownload) {
                triggerDownload(data.url, toFilename(render.moment))
                patch(key, { autoDownload: false })
              }
              return
            }

            if (data?.status === 'error') {
              patch(key, {
                status: 'error',
                error: 'Rendering failed for this one. Try it again.',
              })
              return
            }

            patch(key, { status: data?.status || 'queued' })
          } catch (error) {
            if (!cancelled) {
              patch(key, {
                status: 'error',
                error: getReadableError(error, 'The clip status could not be checked.'),
              })
            }
          }
        }),
      )
    }

    const intervalId = window.setInterval(poll, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [patch, runWithToken])

  return { renders, start, seed, clear }
}
