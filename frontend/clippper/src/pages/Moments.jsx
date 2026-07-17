import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import MomentCard from '../components/MomentCard'
import EmptyState from '../components/EmptyState'
import StatusPill from '../components/StatusPill'
import { ScissorsIcon } from '../components/icons'
import { createClip, getVideoMoments } from '../services/api'
import { useAuthedApi } from '../hooks/useAuthedApi'
import { formatClock } from '../lib/format'
import { getReadableError } from '../lib/errors'

function getFinalScore(moment) {
  const value = Number(moment?.scores?.final)
  return Number.isFinite(value) ? value : 0
}

function Moments() {
  const { videoId } = useParams()
  const navigate = useNavigate()
  const { runWithToken } = useAuthedApi()

  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [generatingIndex, setGeneratingIndex] = useState(null)

  // Best moments first — that ordering is the whole point of the screen.
  const moments = useMemo(() => {
    const list = Array.isArray(data?.moments) ? [...data.moments] : []
    return list.sort((a, b) => getFinalScore(b) - getFinalScore(a))
  }, [data])

  const loadMoments = useCallback(async () => {
    if (!videoId) {
      setError('Video ID is missing.')
      setIsLoading(false)
      return
    }

    try {
      setIsLoading(true)
      setError('')
      const momentsData = await runWithToken((token) => getVideoMoments({ token, videoId }))
      setData(momentsData)
    } catch (loadError) {
      setError(getReadableError(loadError, 'Moments could not be loaded.'))
    } finally {
      setIsLoading(false)
    }
  }, [runWithToken, videoId])

  useEffect(() => {
    // Deferred a tick so the load doesn't set state from the effect body.
    const timeoutId = window.setTimeout(loadMoments, 0)
    return () => window.clearTimeout(timeoutId)
  }, [loadMoments])

  // Rendering is queued on a worker, so we hand the clip id to the viewer and
  // let it poll rather than blocking this page.
  const handleGenerate = useCallback(
    async ({ moment, index, format, captions }) => {
      const startSec = Number(moment.start_sec)
      const endSec = Number(moment.end_sec)

      try {
        setGeneratingIndex(index)
        setError('')

        const clip = await runWithToken((token) =>
          createClip({ videoId, startSec, endSec, format, captions, momentId: moment.id, token }),
        )

        navigate(`/videos/${videoId}/moments/${index}/clip`, {
          state: {
            clipId: clip.clip_id,
            startSec,
            endSec,
            format,
            captions,
            title: moment.title,
          },
        })
      } catch (createError) {
        setError(getReadableError(createError, 'The clip could not be queued.'))
        setGeneratingIndex(null)
      }
    },
    [navigate, runWithToken, videoId],
  )

  const isAnalyzing = data?.status === 'processing' || data?.status === 'uploaded'

  return (
    <AppLayout
      eyebrow="Moments"
      title={data?.filename || 'Your best moments'}
      actions={
        <>
          <Link className="button button-secondary" to="/videos">
            Back to library
          </Link>
          <button className="button button-secondary" disabled={isLoading} onClick={loadMoments} type="button">
            {isLoading ? 'Refreshing…' : 'Refresh'}
          </button>
        </>
      }
    >
      <div className="moments-summary">
        {data?.status ? <StatusPill status={data.status} /> : null}
        {moments.length ? (
          <span>
            {moments.length} moments worth posting — you're one click away from {moments.length} clips.
          </span>
        ) : null}
        {data?.duration != null ? <span className="mono">{formatClock(data.duration, { includeHours: true })}</span> : null}
      </div>

      {error ? <p className="message error">{error}</p> : null}

      {isLoading ? (
        <div className="moment-list">
          {Array.from({ length: 3 }, (_, index) => (
            <div className="skeleton skeleton-card" key={index} />
          ))}
        </div>
      ) : moments.length ? (
        <div className="moment-list">
          {moments.map((moment, index) => (
            <MomentCard
              index={index}
              isGenerating={generatingIndex === index}
              isTop={index === 0}
              key={moment.id || index}
              moment={moment}
              onGenerate={handleGenerate}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          action={
            <Link className="button button-secondary" to="/videos">
              Back to library
            </Link>
          }
          description={
            isAnalyzing
              ? "We're still watching this one. Moments show up here as soon as the analysis finishes — usually a few minutes."
              : 'No moments were found in this video. Try a longer stream, or cut a clip manually.'
          }
          glyph={<ScissorsIcon size={22} />}
          title={isAnalyzing ? 'Still analyzing' : 'No moments found'}
        />
      )}
    </AppLayout>
  )
}

export default Moments
