import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import DashboardLayout from '../components/DashboardLayout'
import { ApiError, createClip, getVideoMetadata } from '../services/api'
import { useAuthedApi } from '../hooks/useAuthedApi'

const initialForm = {
  start: '0',
  end: '60',
}

function getReadableError(error, fallback) {
  if (error instanceof ApiError) {
    return error.status ? `${error.message} (${error.status})` : error.message
  }

  if (error instanceof Error) {
    return error.message
  }

  return fallback
}

function parseSeconds(value) {
  if (value === '') {
    return Number.NaN
  }

  return Number(value)
}

function formatClock(totalSeconds, { includeHours = false } = {}) {
  const safeSeconds = Number.isFinite(totalSeconds) ? Math.max(0, Math.floor(totalSeconds)) : 0
  const hours = Math.floor(safeSeconds / 3600)
  const minutes = Math.floor((safeSeconds % 3600) / 60)
  const seconds = safeSeconds % 60

  if (includeHours) {
    return [hours, minutes, seconds].map((part) => String(part).padStart(2, '0')).join(':')
  }

  const totalMinutes = Math.floor(safeSeconds / 60)
  return `${String(totalMinutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function buildValidation({ duration, endSec, startSec }) {
  const errors = []

  if (!Number.isFinite(startSec)) {
    errors.push('Start time is required.')
  }

  if (!Number.isFinite(endSec)) {
    errors.push('End time is required.')
  }

  if (!Number.isFinite(startSec) || !Number.isFinite(endSec)) {
    return errors
  }

  if (startSec < 0) {
    errors.push('Start must be 0 seconds or later.')
  }

  if (Number.isFinite(duration) && endSec > duration) {
    errors.push(`End must be at or before ${formatClock(duration, { includeHours: true })}.`)
  }

  if (startSec >= endSec) {
    errors.push('Start must be before end.')
  }

  const clipLength = endSec - startSec

  if (clipLength < 1) {
    errors.push('Clip must be at least 1 second long.')
  }

  if (clipLength > 600) {
    errors.push('Clip must be 600 seconds or shorter.')
  }

  return errors
}

function ClipEditor() {
  const { videoId } = useParams()
  const { runWithToken } = useAuthedApi()
  const [metadata, setMetadata] = useState(null)
  const [metadataError, setMetadataError] = useState('')
  const [isMetadataLoading, setIsMetadataLoading] = useState(true)
  const [form, setForm] = useState(initialForm)
  const [clips, setClips] = useState([])
  const [submitError, setSubmitError] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [showHours, setShowHours] = useState(false)

  const startSec = useMemo(() => parseSeconds(form.start), [form.start])
  const endSec = useMemo(() => parseSeconds(form.end), [form.end])
  const validationErrors = useMemo(
    () => buildValidation({ duration: metadata?.duration, endSec, startSec }),
    [endSec, metadata?.duration, startSec],
  )
  const canCreateClip = !isMetadataLoading && !isCreating && !metadataError && validationErrors.length === 0
  const metadataPath = videoId ? `/videos/${videoId}/metadata` : '/videos/{video_id}/metadata'

  const loadMetadata = useCallback(async () => {
    if (!videoId) {
      setMetadataError('Video ID is missing.')
      setIsMetadataLoading(false)
      return
    }

    try {
      setIsMetadataLoading(true)
      setMetadataError('')
      const data = await runWithToken((token) => getVideoMetadata({ videoId, token }))
      setMetadata(data)
    } catch (error) {
      setMetadataError(getReadableError(error, 'Video metadata could not be loaded.'))
    } finally {
      setIsMetadataLoading(false)
    }
  }, [runWithToken, videoId])

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      loadMetadata()
    }, 0)

    return () => window.clearTimeout(timeoutId)
  }, [loadMetadata])

  function updateField(field, value) {
    setForm((current) => ({
      ...current,
      [field]: value,
    }))
    setSubmitError('')
  }

  async function handleSubmit(event) {
    event.preventDefault()

    if (!canCreateClip) {
      return
    }

    try {
      setIsCreating(true)
      setSubmitError('')
      const data = await runWithToken((token) =>
        createClip({
          endSec,
          startSec,
          token,
          videoId,
        }),
      )

      if (!data?.url || !data?.clip_id) {
        throw new ApiError('The clip was created, but the server response was incomplete.', {
          details: data,
        })
      }

      setClips((current) => [
        {
          clipId: data.clip_id,
          endSec,
          startSec,
          url: data.url,
        },
        ...current,
      ])
    } catch (error) {
      setSubmitError(getReadableError(error, 'The clip could not be created.'))
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <DashboardLayout eyebrow="Clip editor" title="Cut a highlight from this video.">
      <section className="clip-editor-page">
        <div className="clip-editor-topline">
          <Link className="button button-secondary" to="/videos">
            Back to videos
          </Link>
        </div>

        <section className="dashboard-panel clip-metadata-panel">
          <div>
            <p className="panel-label">Source video</p>
            <h2>{isMetadataLoading ? 'Loading metadata...' : metadata?.filename || 'Untitled video'}</h2>
          </div>
          <div className="clip-time-controls">
            <span>
              {metadata?.duration != null
                ? formatClock(metadata.duration, { includeHours: showHours })
                : formatClock(0, { includeHours: showHours })}
            </span>
            <div className="time-format-toggle" aria-label="Time format" role="group">
              <button
                aria-pressed={!showHours}
                className={!showHours ? 'active' : ''}
                onClick={() => setShowHours(false)}
                type="button"
              >
                MM:SS
              </button>
              <button
                aria-pressed={showHours}
                className={showHours ? 'active' : ''}
                onClick={() => setShowHours(true)}
                type="button"
              >
                HH:MM:SS
              </button>
            </div>
          </div>
        </section>

        {metadataError ? (
          <div className="upload-message error metadata-message">
            <span>{metadataError}</span>
            <button className="button button-secondary" type="button" onClick={loadMetadata}>
              Retry metadata
            </button>
          </div>
        ) : null}

        {isMetadataLoading ? (
          <div className="metadata-request-status" aria-live="polite">
            Requesting GET {metadataPath}
          </div>
        ) : null}

        <form className="dashboard-panel clip-form" onSubmit={handleSubmit}>
          <div className="clip-field-grid">
            <label className="clip-field">
              <span>Start time</span>
              <div className="clip-input-row">
                <input
                  min="0"
                  onChange={(event) => updateField('start', event.target.value)}
                  step="0.1"
                  type="number"
                  value={form.start}
                />
                <strong>{formatClock(startSec, { includeHours: showHours })}</strong>
              </div>
            </label>

            <label className="clip-field">
              <span>End time</span>
              <div className="clip-input-row">
                <input
                  min="0"
                  onChange={(event) => updateField('end', event.target.value)}
                  step="0.1"
                  type="number"
                  value={form.end}
                />
                <strong>{formatClock(endSec, { includeHours: showHours })}</strong>
              </div>
            </label>
          </div>

          {validationErrors.length ? (
            <div className="clip-errors" aria-live="polite">
              {validationErrors.map((error) => (
                <p key={error}>{error}</p>
              ))}
            </div>
          ) : null}

          {submitError ? (
            <div className="upload-message error">
              {submitError}
            </div>
          ) : null}

          <button className="button button-primary clip-submit" disabled={!canCreateClip} type="submit">
            {isCreating ? 'Cutting clip...' : 'Cut Clip'}
          </button>
        </form>

        <section className="dashboard-panel created-clips-panel">
          <div className="panel-heading">
            <div>
              <p className="panel-label">{clips.length} clips</p>
              <h2>Created clips</h2>
            </div>
          </div>

          {clips.length ? (
            <div className="created-clips-list">
              {clips.map((clip) => (
                <article className="created-clip" key={clip.clipId}>
                  <div className="created-clip-meta">
                    <strong>
                      {formatClock(clip.startSec, { includeHours: showHours })} -{' '}
                      {formatClock(clip.endSec, { includeHours: showHours })}
                    </strong>
                    <span>{clip.clipId}</span>
                  </div>
                  <video controls src={clip.url}>
                    <track kind="captions" />
                  </video>
                  <a className="button button-secondary clip-download" download href={clip.url}>
                    Download
                  </a>
                </article>
              ))}
            </div>
          ) : (
            <div className="videos-empty">
              <strong>No clips cut yet.</strong>
              <span>Choose a valid start and end time, then cut your first clip.</span>
            </div>
          )}
        </section>
      </section>
    </DashboardLayout>
  )
}

export default ClipEditor
