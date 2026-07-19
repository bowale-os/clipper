import Poster from './Poster'
import { DownloadIcon } from './icons'
import { formatClock, toScore } from '../lib/format'

/**
 * One detected moment, shown as the post it is about to become. The tile opens
 * the preview; the small button underneath is the shortcut for people who
 * already trust the score and just want the file.
 */
function ClipTile({ format, isTop = false, moment, onDownload, onOpen, render }) {
  const isWorking = render?.status === 'queued' || render?.status === 'rendering'
  const title = moment?.title || 'Untitled moment'

  return (
    <article className="clip-tile">
      <Poster
        caption={title}
        format={format}
        isTop={isTop}
        onClick={() => onOpen(moment)}
        score={toScore(moment?.scores?.final)}
      />

      <div className="clip-tile-foot">
        <span className="mono">{formatClock(moment?.start_sec, { includeHours: true })}</span>
        <button
          aria-label={isWorking ? `Making ${title}` : `Download ${title}`}
          className="tile-action"
          disabled={isWorking}
          onClick={() => onDownload(moment)}
          title={isWorking ? 'Making this one now' : 'Download'}
          type="button"
        >
          <DownloadIcon size={14} />
        </button>
      </div>
    </article>
  )
}

export default ClipTile
