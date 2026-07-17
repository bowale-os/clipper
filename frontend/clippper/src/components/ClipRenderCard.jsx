import StatusPill from './StatusPill'
import { DownloadIcon } from './icons'
import { useClipStatus } from '../hooks/useClipStatus'
import { formatClock } from '../lib/format'

const waitCopy = {
  queued: 'Your clip is in the queue — this usually takes under a minute.',
  rendering: 'Rendering now. Cutting, cropping, and burning in captions.',
}

/**
 * A single queued render. Owns its own polling so several clips can render at
 * once without the page coordinating them.
 */
function ClipRenderCard({ clipId, startSec, endSec, format, captions }) {
  const { status, url, error } = useClipStatus(clipId)

  return (
    <article className="clip-render">
      <div className="clip-render-head">
        <div>
          <strong>
            {formatClock(startSec)} – {formatClock(endSec)}
          </strong>
          <p className="mono">
            {format}
            {captions ? ' · captions' : ''}
          </p>
        </div>
        <StatusPill status={status} />
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
        <div className="clip-render-wait">
          <span>{waitCopy[status]}</span>
          <div className="progress-track is-indeterminate">
            <span />
          </div>
        </div>
      ) : null}

      {error ? <p className="message error">{error}</p> : null}
    </article>
  )
}

export default ClipRenderCard
