import { useEffect, useRef, useState } from 'react'
import Poster from './Poster'
import LiveStatus from './LiveStatus'
import { CloseIcon, DownloadIcon } from './icons'
import { CLIP_FORMATS } from '../services/api'
import { formatClock, toScore } from '../lib/format'

const scoreLabels = [
  ['hook', 'Hook'],
  ['shareability', 'Shareable'],
  ['completeness', 'Complete'],
  ['visual', 'Visual'],
]

const shapeCopy = {
  '9:16': 'Tall',
  '1:1': 'Square',
  '16:9': 'Wide',
}

const waitCopy = {
  queued: 'In the queue. This usually takes under a minute.',
  rendering: 'Making it now. Cutting, cropping, and burning the captions in.',
  processing: 'Making it now.',
}

/**
 * Sits over the main screen when you tap a clip. Rendering happens here, on
 * demand, because a moment is only worth paying to render once you have decided
 * you want it.
 */
function ClipPreview({ captions, format, moment, onClose, onRender, render }) {
  const closeRef = useRef(null)
  const activeFormat = render?.format || format
  const activeCaptions = typeof render?.captions === 'boolean' ? render.captions : captions

  // What the buttons below are asking for, which is not always what is on
  // screen. Nothing renders until the one primary button is pressed, so picking
  // a different shape never quietly costs a render.
  const cutKey = `${activeFormat}|${activeCaptions}`
  const [picked, setPicked] = useState({
    captions: activeCaptions,
    key: cutKey,
    shape: activeFormat,
  })

  // A finished render becomes the new starting point for the picks.
  if (picked.key !== cutKey) {
    setPicked({ captions: activeCaptions, key: cutKey, shape: activeFormat })
  }

  const wantShape = picked.shape
  const wantCaptions = picked.captions
  const setWantShape = (shape) => setPicked((current) => ({ ...current, shape }))
  const setWantCaptions = (value) => setPicked((current) => ({ ...current, captions: value }))

  useEffect(() => {
    closeRef.current?.focus()

    function handleKey(event) {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose])

  const status = render?.status
  const isWorking = status === 'queued' || status === 'rendering' || status === 'processing'
  const isReady = status === 'ready' && render?.url
  const title = moment?.title || 'Untitled moment'
  const shapeChanged = wantShape !== activeFormat
  const captionsChanged = wantCaptions !== activeCaptions
  const isSameCut = !shapeChanged && !captionsChanged

  // Say back exactly what changed, so the button reads as the thing about to
  // happen rather than a generic redo.
  const redoCopy = [
    shapeChanged ? `as ${shapeCopy[wantShape].toLowerCase()}` : '',
    captionsChanged ? (wantCaptions ? 'with captions' : 'without captions') : '',
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <div
      className="scrim"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose()
        }
      }}
      role="presentation"
    >
      <div
        className={`preview-card${isReady ? ' is-playable' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        {isReady ? (
          <video className="preview-video" controls src={render.url}>
            <track kind="captions" />
          </video>
        ) : (
          <Poster
            caption={title}
            format={activeFormat}
            isTop
            score={toScore(moment?.scores?.final)}
            showFormat={false}
          />
        )}

        <div className="preview-body">
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <h2>{title}</h2>
              <span className="mono">
                {formatClock(moment?.start_sec, { includeHours: true })} to{' '}
                {formatClock(moment?.end_sec, { includeHours: true })}
              </span>
            </div>
            <button
              aria-label="Close"
              className="icon-button"
              onClick={onClose}
              ref={closeRef}
              type="button"
            >
              <CloseIcon size={16} />
            </button>
          </div>

          {moment?.reason ? <p className="preview-reason">{moment.reason}</p> : null}

          <div className="score-chips">
            {scoreLabels.map(([key, label]) => {
              const value = toScore(moment?.scores?.[key])
              return value == null ? null : (
                <span className="score-chip" key={key}>
                  {label} <strong>{value}</strong>
                </span>
              )
            })}
          </div>

          {isWorking ? (
            <div className="preview-wait" aria-live="polite">
              <LiveStatus status={status} />
              <span>{waitCopy[status]}</span>
              <div className="progress-track is-indeterminate">
                <span />
              </div>
            </div>
          ) : null}

          {render?.error ? <p className="message error">{render.error}</p> : null}

          <div className="preview-options">
            <div className="preview-option">
              <span>Shape</span>
              <div className="segmented" role="group" aria-label="Clip shape">
                {CLIP_FORMATS.map((shape) => (
                  <button
                    aria-pressed={wantShape === shape}
                    disabled={isWorking}
                    key={shape}
                    onClick={() => setWantShape(shape)}
                    type="button"
                  >
                    {shapeCopy[shape]}
                  </button>
                ))}
              </div>
            </div>

            <div className="preview-option">
              <span>Captions</span>
              <div className="segmented" role="group" aria-label="Captions">
                <button
                  aria-pressed={wantCaptions}
                  disabled={isWorking}
                  onClick={() => setWantCaptions(true)}
                  type="button"
                >
                  On
                </button>
                <button
                  aria-pressed={!wantCaptions}
                  disabled={isWorking}
                  onClick={() => setWantCaptions(false)}
                  type="button"
                >
                  Off
                </button>
              </div>
            </div>
          </div>

          <div className="preview-actions">
            {isReady && isSameCut ? (
              <a className="button button-primary button-block" download href={render.url}>
                <DownloadIcon size={16} />
                Download
              </a>
            ) : (
              <button
                className="button button-primary button-block"
                disabled={isWorking}
                onClick={() =>
                  onRender({ moment, format: wantShape, captions: wantCaptions })
                }
                type="button"
              >
                {isWorking ? 'Making it…' : isReady ? `Make it ${redoCopy}` : 'Make this clip'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default ClipPreview
