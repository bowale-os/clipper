import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import ClipRenderCard from '../components/ClipRenderCard'
import EmptyState from '../components/EmptyState'
import FormatPicker from '../components/FormatPicker'
import Toggle from '../components/Toggle'
import { ScissorsIcon } from '../components/icons'
import { DEFAULT_CLIP_FORMAT, createClip, getVideoMetadata } from '../services/api'
import { useAuthedApi } from '../hooks/useAuthedApi'
import { formatClock } from '../lib/format'
import { getReadableError } from '../lib/errors'

const MAX_CLIP_SEC = 600

function parseSeconds(value) {
  return value === '' ? Number.NaN : Number(value)
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

  if (clipLength >= 1 && clipLength > MAX_CLIP_SEC) {
    errors.push(`Clips can be at most ${MAX_CLIP_SEC / 60} minutes long.`)
  } else if (clipLength < 1) {
    errors.push('Clip must be at least 1 second long.')
  }

  return errors
}

function ClipEditor() {
  const { videoId } = useParams()
  const { runWithToken } = useAuthedApi()

  const [metadata, setMetadata] = useState(null)
  const [metadataError, setMetadataError] = useState('')
  const [isMetadataLoading, setIsMetadataLoading] = useState(true)
  const [form, setForm] = useState({ start: '0', end: '60' })
  const [format, setFormat] = useState(DEFAULT_CLIP_FORMAT)
  const [captions, setCaptions] = useState(true)
  const [clips, setClips] = useState([])
  const [submitError, setSubmitError] = useState('')
  const [isCreating, setIsCreating] = useState(false)

  const startSec = useMemo(() => parseSeconds(form.start), [form.start])
  const endSec = useMemo(() => parseSeconds(form.end), [form.end])
  const validationErrors = useMemo(
    () => buildValidation({ duration: metadata?.duration, endSec, startSec }),
    [endSec, metadata?.duration, startSec],
  )
  const canCreateClip = !isMetadataLoading && !isCreating && !metadataError && validationErrors.length === 0

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
    // Deferred a tick so the load doesn't set state from the effect body.
    const timeoutId = window.setTimeout(loadMetadata, 0)
    return () => window.clearTimeout(timeoutId)
  }, [loadMetadata])

  function updateField(field, value) {
    setForm((current) => ({ ...current, [field]: value }))
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

      const clip = await runWithToken((token) =>
        createClip({ videoId, startSec, endSec, format, captions, token }),
      )

      // The render is queued; each card polls itself until its file lands.
      setClips((current) => [{ clipId: clip.clip_id, startSec, endSec, format, captions }, ...current])
    } catch (error) {
      setSubmitError(getReadableError(error, 'The clip could not be queued.'))
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <AppLayout
      eyebrow="Manual cut"
      title={isMetadataLoading ? 'Loading video…' : metadata?.filename || 'Untitled video'}
      actions={
        <Link className="button button-secondary" to="/videos">
          Back to library
        </Link>
      }
    >
      {metadataError ? (
        <div className="message error">
          <span>{metadataError}</span>
          <button className="button button-secondary" type="button" onClick={loadMetadata}>
            Retry
          </button>
        </div>
      ) : null}

      <div className="clip-editor-grid">
        <form className="card" onSubmit={handleSubmit}>
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Trim</p>
              <h2>Pick your in and out</h2>
            </div>
            {metadata?.duration != null ? (
              <span className="mono">{formatClock(metadata.duration, { includeHours: true })} total</span>
            ) : null}
          </div>

          <div className="clip-field-row">
            <label className="field">
              <span>Start (seconds)</span>
              <input
                className="input"
                min="0"
                onChange={(event) => updateField('start', event.target.value)}
                step="0.1"
                type="number"
                value={form.start}
              />
              <span className="clip-field-hint">{formatClock(startSec, { includeHours: true })}</span>
            </label>

            <label className="field">
              <span>End (seconds)</span>
              <input
                className="input"
                min="0"
                onChange={(event) => updateField('end', event.target.value)}
                step="0.1"
                type="number"
                value={form.end}
              />
              <span className="clip-field-hint">{formatClock(endSec, { includeHours: true })}</span>
            </label>
          </div>

          <div className="clip-form-options">
            <FormatPicker disabled={isCreating} onChange={setFormat} value={format} />
            <Toggle checked={captions} disabled={isCreating} label="Captions" onChange={setCaptions} />
          </div>

          {validationErrors.length ? (
            <div className="clip-errors" aria-live="polite">
              {validationErrors.map((error) => (
                <p key={error}>{error}</p>
              ))}
            </div>
          ) : null}

          {submitError ? <p className="message error">{submitError}</p> : null}

          <button className="button button-primary button-large button-block" disabled={!canCreateClip} type="submit">
            {isCreating ? 'Sending to render…' : 'Cut this clip'}
          </button>
        </form>

        <section className="card">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{clips.length} clips</p>
              <h2>Your cuts</h2>
            </div>
          </div>

          {clips.length ? (
            <div className="clip-results">
              {clips.map((clip) => (
                <ClipRenderCard
                  captions={clip.captions}
                  clipId={clip.clipId}
                  endSec={clip.endSec}
                  format={clip.format}
                  key={clip.clipId}
                  startSec={clip.startSec}
                />
              ))}
            </div>
          ) : (
            <EmptyState
              description="Set a start and end, then cut. Clips render in the background and show up right here."
              glyph={<ScissorsIcon size={22} />}
              title="No cuts yet"
            />
          )}
        </section>
      </div>
    </AppLayout>
  )
}

export default ClipEditor
