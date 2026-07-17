import { Link } from 'react-router-dom'
import StatusPill from './StatusPill'
import { FilmIcon, TrashIcon } from './icons'
import { formatBytes, formatDate, getFileExtension, getVideoId } from '../lib/format'

/**
 * The backend stores no thumbnails yet, so the poster area is a flat placeholder
 * carrying the status and file type rather than a fake image.
 */
function VideoCard({ video, onDelete, onResume, isDeleting = false }) {
  const videoId = getVideoId(video)
  const status = video?.status || 'unknown'
  const clipsPath = `/videos/${encodeURIComponent(videoId)}/clips`
  const momentsPath = `/videos/${encodeURIComponent(videoId)}/moments`

  return (
    <article className="video-card">
      <div className="thumb">
        <FilmIcon size={28} />
        <StatusPill className="thumb-status" status={status} />
        <span className="thumb-ext">{getFileExtension(video?.filename)}</span>
      </div>

      <div className="video-card-body">
        <h3 title={video?.filename || 'Untitled video'}>{video?.filename || 'Untitled video'}</h3>
        <p className="video-card-meta">
          {formatBytes(video?.size_bytes ?? video?.size)} · {formatDate(video?.created_at)}
        </p>
      </div>

      <div className="video-card-actions">
        {status === 'ready' ? (
          <>
            <Link className="button button-primary" to={momentsPath}>
              Find clips
            </Link>
            <Link className="button button-secondary" to={clipsPath}>
              Manual cut
            </Link>
          </>
        ) : null}

        {status === 'uploading' && onResume ? (
          <button className="button button-primary" onClick={() => onResume(video)} type="button">
            Resume upload
          </button>
        ) : null}

        {['uploaded', 'processing'].includes(status) ? (
          <span className="video-card-meta">Finding your best moments…</span>
        ) : null}

        {status === 'error' ? <span className="video-card-meta">This one didn’t make it through.</span> : null}

        {onDelete ? (
          <button
            aria-label={`Delete ${video?.filename || 'video'}`}
            className="button button-danger"
            disabled={isDeleting}
            onClick={() => onDelete(video)}
            type="button"
          >
            <TrashIcon size={16} />
          </button>
        ) : null}
      </div>
    </article>
  )
}

export default VideoCard
