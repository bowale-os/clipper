import { useEffect, useRef } from 'react'
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

const otherShapeCopy = {
  '1:1': 'Make it square instead',
  '16:9': 'Make it wide instead',
  '9:16': 'Make it tall instead',
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
function ClipPreview({ format, moment, onClose, onRender, render }) {
  const closeRef = useRef(null)

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
  const activeFormat = render?.format || format
  const otherShapes = CLIP_FORMATS.filter((shape) => shape !== activeFormat)
  const title = moment?.title || 'Untitled moment'

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
      <div className="preview-card" role="dialog" aria-modal="true" aria-label={title}>
        {isReady ? (
          <video className="preview-video" controls src={render.url} style={{ gridColumn: '1 / -1' }}>
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

          <div className="preview-actions">
            {isReady ? (
              <a className="button button-primary button-block" download href={render.url}>
                <DownloadIcon size={16} />
                Download
              </a>
            ) : (
              <button
                className="button button-primary button-block"
                disabled={isWorking}
                onClick={() => onRender({ moment, format: activeFormat })}
                type="button"
              >
                {isWorking ? 'Making it…' : 'Make this clip'}
              </button>
            )}

            {otherShapes.map((shape) => (
              <button
                className="button button-quiet button-small button-block"
                disabled={isWorking}
                key={shape}
                onClick={() => onRender({ moment, format: shape })}
                type="button"
              >
                {otherShapeCopy[shape]}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default ClipPreview
