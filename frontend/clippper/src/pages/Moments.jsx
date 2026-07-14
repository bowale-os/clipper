import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import DashboardLayout from '../components/DashboardLayout'
import { ApiError, getVideoMoments, createClip } from '../services/api'
import { useAuthedApi } from '../hooks/useAuthedApi'

function getReadableError(error) {
  if (error instanceof ApiError) {
    return error.status ? `${error.message} (${error.status})` : error.message
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Moments could not be loaded.'
}

function formatClock(totalSeconds) {
  const safeSeconds = Number.isFinite(Number(totalSeconds)) ? Math.max(0, Math.floor(Number(totalSeconds))) : 0
  const hours = Math.floor(safeSeconds / 3600)
  const minutes = Math.floor((safeSeconds % 3600) / 60)
  const seconds = safeSeconds % 60

  if (hours > 0) {
    return [hours, minutes, seconds].map((part) => String(part).padStart(2, '0')).join(':')
  }
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function getMomentStart(moment) {
  return moment?.start_sec ?? moment?.start ?? moment?.start_time ?? moment?.timestamp ?? 0
}

function getMomentEnd(moment) {
  return moment?.end_sec ?? moment?.end ?? moment?.end_time ?? null
}

function getMomentTitle(moment, index) {
  return moment?.title || moment?.headline || moment?.label || moment?.summary || `Moment ${index + 1}`
}

function getMomentDescription(moment) {
  return moment?.description || moment?.reason || moment?.text || moment?.transcript || moment?.hook || ''
}

function getMomentScore(moment) {
  return moment?.score ?? moment?.confidence ?? moment?.rating ?? null
}

function MomentCard({ index, moment, videoId, onCreateClip, isCreating }) {
  const start = getMomentStart(moment)
  const end = getMomentEnd(moment)
  const score = getMomentScore(moment)
  const description = getMomentDescription(moment)

  const handleGetClip = () => {
    onCreateClip(moment, index)
  }

  return (
    <article className="moment-card">
      <div className="moment-card-header">
        <div>
          <p className="panel-label">
            {formatClock(start)}
            {end != null ? ` - ${formatClock(end)}` : ''}
          </p>
          <h3>{getMomentTitle(moment, index)}</h3>

          <button 
            className="button button-primary"
            onClick={handleGetClip}
            disabled={isCreating === index}
          >
            {isCreating === index ? 'Creating Clip...' : 'Get Clip'}
          </button>
        </div>
        
        {score != null && <span className="moment-score">{score}</span>}
      </div>

      {description && <p className="moment-description">{description}</p>}
    </article>
  )
}

function Moments() {
  const { videoId } = useParams()
  const navigate = useNavigate()
  const { runWithToken } = useAuthedApi()

  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [creatingClipFor, setCreatingClipFor] = useState(null)

  const moments = useMemo(() => (Array.isArray(data?.moments) ? data.moments : []), [data?.moments])

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
      setError(getReadableError(loadError))
    } finally {
      setIsLoading(false)
    }
  }, [runWithToken, videoId])

  const handleCreateClip = useCallback(async (moment, index) => {
    const startSec = getMomentStart(moment)
    let endSec = getMomentEnd(moment)

    if (endSec == null) {
      endSec = Math.min(startSec + 30, data?.duration || startSec + 30)
    }

    try {
      setCreatingClipFor(index)

      const clipData = await runWithToken((token) =>
        createClip({ videoId, startSec, endSec, token })
      )

      if (!clipData?.url) {
        throw new Error('Clip created but no URL was returned')
      }

      navigate(`/videos/${videoId}/moments/${index}/clip`, {
        state: { 
          clipUrl: clipData.url, 
          clipId: clipData.clip_id, 
          startSec, 
          endSec 
        }
      })
    } catch (err) {
      alert(`Failed to create clip: ${err.message || 'Unknown error'}`)
    } finally {
      setCreatingClipFor(null)
    }
  }, [runWithToken, videoId, navigate, data?.duration])

  useEffect(() => {
    loadMoments()
  }, [loadMoments])

  return (
    <DashboardLayout eyebrow="Detected moments" title={data?.filename || 'Video moments'}>
      <section className="moments-page">
        <div className="videos-toolbar">
          <div>
            <p className="panel-label">Review</p>
            <h2>Top moments, ranked</h2>
          </div>
          <div className="moments-toolbar-actions">
            <Link className="button button-secondary" to="/videos">
              Back to videos
            </Link>
            <button 
              className="button button-secondary" 
              type="button" 
              onClick={loadMoments} 
              disabled={isLoading}
            >
              {isLoading ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>
        </div>

        {error && <div className="upload-message error">{error}</div>}

        {isLoading ? (
          <div className="dashboard-panel videos-loading">Loading moments...</div>
        ) : (
          <section className="dashboard-panel moments-panel">
            <div className="panel-heading">
              <div>
                <p className="panel-label">{data?.status || 'unknown'} status</p>
                <h2>{moments.length} detected moments</h2>
              </div>
              {data?.duration != null && (
                <span className="moment-duration">{formatClock(data.duration)}</span>
              )}
            </div>

            {moments.length > 0 ? (
              <div className="moments-list">
                {moments.map((moment, index) => (
                  <MomentCard
                    key={`${getMomentStart(moment)}-${index}`}
                    index={index}
                    moment={moment}
                    videoId={videoId}
                    onCreateClip={handleCreateClip}
                    isCreating={creatingClipFor}
                  />
                ))}
              </div>
            ) : (
              <div className="videos-empty">
                <strong>No moments yet.</strong>
                <span>Analysis may still be running — check back in a few minutes.</span>
              </div>
            )}
          </section>
        )}
      </section>
    </DashboardLayout>
  )
}

export default Moments