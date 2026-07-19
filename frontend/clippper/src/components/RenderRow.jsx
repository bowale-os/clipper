import LiveStatus from './LiveStatus'
import { DownloadIcon } from './icons'
import { useClipStatus } from '../hooks/useClipStatus'
import { formatClock } from '../lib/format'

const waitCopy = {
  queued: 'In the queue. This usually takes under a minute.',
  rendering: 'Making it now. Cutting, cropping, and burning the captions in.',
}

/**
 * One queued manual cut. Owns its own polling so several can render at once
 * without the page having to coordinate them.
 */
function RenderRow({ captions, clipId, endSec, format, startSec }) {
  const { status, url, error } = useClipStatus(clipId)

  return (
    <article className="render-row">
      <div className="render-row-head">
        <div>
          <strong>
            {formatClock(startSec, { includeHours: true })} to{' '}
            {formatClock(endSec, { includeHours: true })}
          </strong>
          <p className="mono">
            {format}
            {captions ? ' · captions' : ''}
          </p>
        </div>
        <LiveStatus status={status} />
      </div>

      {status === 'ready' && url ? (
        <>
          <video controls src={url}>
            <track kind="captions" />
          </video>
          <a className="button button-secondary" download href={url}>
            <DownloadIcon size={16} />
            Download
          </a>
        </>
      ) : null}

      {status === 'queued' || status === 'rendering' ? (
        <div>
          <p className="muted" style={{ marginBottom: 'var(--space-3)', fontSize: 'var(--text-sm)' }}>
            {waitCopy[status]}
          </p>
          <div className="progress-track is-indeterminate">
            <span />
          </div>
        </div>
      ) : null}

      {error ? <p className="message error">{error}</p> : null}
    </article>
  )
}

export default RenderRow
