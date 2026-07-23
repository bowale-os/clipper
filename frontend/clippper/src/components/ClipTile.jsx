import Poster from './Poster'
import { DownloadIcon } from './icons'
import { formatClock, toScore } from '../lib/format'
import { getMomentScore } from '../lib/moments'

/**
 * One detected moment, shown as the post it is about to become. The tile opens
 * the preview; the small button underneath is the shortcut for people who
 * already trust the score and just want the file.
 *
 * `scoreKey` is the order the grid is in: the badge shows that rating so its number
 * always explains the position the tile is sitting in. `previousPlace`, when set, is where
 * this clip sat before the last sort flip.
 */
function ClipTile({
  format,
  isTop = false,
  moment,
  onDownload,
  onOpen,
  previousPlace,
  render,
  scoreKey = 'final',
}) {
  const isWorking = render?.status === 'queued' || render?.status === 'rendering'
  const title = moment?.title || 'Untitled moment'

  // Only name the rating when it isn't the overall score — an unlabelled number reads as
  // "the score", and that's exactly what the default order shows.
  const scoreLabel = scoreKey === 'final' ? '' : scoreKey

  return (
    <article className="clip-tile">
      <Poster
        boxed
        caption={title}
        format={format}
        isTop={isTop}
        onClick={() => onOpen(moment)}
        previousPlace={previousPlace}
        score={toScore(getMomentScore(moment, scoreKey))}
        scoreLabel={scoreLabel}
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
