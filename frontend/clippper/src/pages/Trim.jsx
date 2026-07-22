import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import TopBar from '../components/TopBar'
import RenderRow from '../components/RenderRow'
import EmptyState from '../components/EmptyState'
import FormatPicker from '../components/FormatPicker'
import Toggle from '../components/Toggle'
import { ArrowLeftIcon, ScissorsIcon } from '../components/icons'
import { createClip, getVideoMetadata } from '../services/api'
import { useAuthedApi } from '../hooks/useAuthedApi'
import { usePrefs } from '../hooks/usePrefs'
import { formatClock, parseTimecode } from '../lib/format'
import { getReadableError } from '../lib/errors'

const MAX_CLIP_SEC = 600

function buildValidation({ duration, endSec, startSec }) {
  const errors = []

  if (!Number.isFinite(startSec)) {
    errors.push('Start time should look like 1:30 or 01:02:30.')
  }

  if (!Number.isFinite(endSec)) {
    errors.push('End time should look like 1:30 or 01:02:30.')
  }

  if (!Number.isFinite(startSec) || !Number.isFinite(endSec)) {
    return errors
  }

  if (startSec < 0) {
    errors.push('Start must be zero or later.')
  }

  if (Number.isFinite(duration) && endSec > duration) {
    errors.push(`This video ends at ${formatClock(duration, { includeHours: true })}.`)
  }

  if (startSec >= endSec) {
    errors.push('Start must come before end.')
  }

  const clipLength = endSec - startSec

  if (clipLength >= 1 && clipLength > MAX_CLIP_SEC) {
    errors.push(`Clips can be at most ${MAX_CLIP_SEC / 60} minutes long.`)
  } else if (clipLength < 1) {
    errors.push('A clip needs to be at least a second long.')
  }

  return errors
}

/**
 * The escape hatch for when the detector missed something. Not in the nav — you
 * get here from a stream on the main screen, because that is the only time you
 * would want it.
 */
function Trim() {
  const { videoId } = useParams()
  const { runWithToken } = useAuthedApi()
  const { prefs } = usePrefs()

  const [metadata, setMetadata] = useState(null)
  const [metadataError, setMetadataError] = useState('')
  const [isMetadataLoading, setIsMetadataLoading] = useState(true)
  const [form, setForm] = useState({ start: '0:00', end: '1:00' })
  const [format, setFormat] = useState(prefs.format)
  const [captions, setCaptions] = useState(prefs.captions)
  const [clips, setClips] = useState([])
  const [submitError, setSubmitError] = useState('')
  const [isCreating, setIsCreating] = useState(false)

  const startSec = useMemo(() => parseTimecode(form.start), [form.start])
  const endSec = useMemo(() => parseTimecode(form.end), [form.end])
  const validationErrors = useMemo(
    () => buildValidation({ duration: metadata?.duration, endSec, startSec }),
    [endSec, metadata?.duration, startSec],
  )
  const canCreateClip = !isMetadataLoading && !isCreating && !metadataError && !validationErrors.length

  const loadMetadata = useCallback(async () => {
    if (!videoId) {
      setMetadataError('That video is missing an id.')
      setIsMetadataLoading(false)
      return
    }

    try {
      setIsMetadataLoading(true)
      setMetadataError('')
      const data = await runWithToken((token) => getVideoMetadata({ videoId, token }))
      setMetadata(data)
    } catch (error) {
      setMetadataError(getReadableError(error, 'That video could not be loaded.'))
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

      // The render is queued; each row polls itself until its file lands.
      setClips((current) => [{ clipId: clip.clip_id, startSec, endSec, format, captions }, ...current])
    } catch (error) {
      setSubmitError(getReadableError(error, 'That clip could not be queued.'))
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <div className="app-shell">
      <div className="app-content">
        <TopBar />

        <div className="page-header">
          <div>
            <p className="eyebrow">Cut your own</p>
            <h1>{isMetadataLoading ? 'Loading…' : metadata?.filename || 'Untitled video'}</h1>
          </div>
          <Link className="button button-quiet" to="/">
            <ArrowLeftIcon size={16} />
            Back to your clips
          </Link>
        </div>

        {metadataError ? (
          <p className="message error" style={{ marginBottom: 'var(--space-5)' }}>
            {metadataError}
          </p>
        ) : null}

        <div className="trim-layout">
          <form className="card" onSubmit={handleSubmit}>
            <div className="section-head" style={{ marginTop: 0 }}>
              <h2>Pick your in and out</h2>
              {metadata?.duration != null ? (
                <span className="mono">{formatClock(metadata.duration, { includeHours: true })} long</span>
              ) : null}
            </div>

            <div className="trim-fields">
              <label className="field">
                <span>Starts at</span>
                <input
                  className="input"
                  inputMode="numeric"
                  onChange={(event) => updateField('start', event.target.value)}
                  placeholder="0:00"
                  type="text"
                  value={form.start}
                />
                <span className="field-hint">
                  {Number.isFinite(startSec) ? formatClock(startSec, { includeHours: true }) : '·'}
                </span>
              </label>

              <label className="field">
                <span>Ends at</span>
                <input
                  className="input"
                  inputMode="numeric"
                  onChange={(event) => updateField('end', event.target.value)}
                  placeholder="1:00"
                  type="text"
                  value={form.end}
                />
                <span className="field-hint">
                  {Number.isFinite(endSec) ? formatClock(endSec, { includeHours: true }) : '·'}
                </span>
              </label>
            </div>

            <div className="trim-options">
              <FormatPicker disabled={isCreating} onChange={setFormat} value={format} />
              <Toggle checked={captions} disabled={isCreating} label="Captions" onChange={setCaptions} />
            </div>

            {validationErrors.length ? (
              <div className="trim-errors" aria-live="polite">
                {validationErrors.map((error) => (
                  <p key={error}>{error}</p>
                ))}
              </div>
            ) : null}

            {submitError ? (
              <p className="message error" style={{ marginBottom: 'var(--space-4)' }}>
                {submitError}
              </p>
            ) : null}

            <button className="button button-primary button-large button-block" disabled={!canCreateClip} type="submit">
              {isCreating ? 'Sending it off…' : 'Cut this clip'}
            </button>
          </form>

          <section>
            <div className="section-head" style={{ marginTop: 0 }}>
              <h2>Your cuts</h2>
            </div>

            {clips.length ? (
              <div className="trim-results">
                {clips.map((clip) => (
                  <RenderRow
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
                description="Set a start and an end, then cut. Clips render in the background and turn up right here."
                glyph={<ScissorsIcon size={22} />}
                title="No cuts yet"
              />
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

export default Trim
