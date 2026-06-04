import { useLocation, useParams, Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import DashboardLayout from '../components/DashboardLayout'

function MomentClipViewer() {
  const { videoId, momentIndex } = useParams()
  const location = useLocation()
  const { clipUrl, clipId, startSec, endSec } = location.state || {}

  const [videoError, setVideoError] = useState(false)

  if (!clipUrl) {
    return (
      <DashboardLayout eyebrow="Clip Viewer" title="Error">
        <div className="upload-message error">
          No clip URL available. Go back and try again.
        </div>
        <Link to={`/videos/${videoId}/moments`} className="button button-secondary">
          ← Back to Moments
        </Link>
      </DashboardLayout>
    )
  }

  return (
    <DashboardLayout 
      eyebrow="Moment Clip" 
      title={`Moment ${Number(momentIndex) + 1}`}
    >
      <section className="moment-clip-viewer">
        <Link to={`/videos/${videoId}/moments`} className="button button-secondary">
          ← Back to Moments
        </Link>

        <div className="clip-player-container">
          <div className="clip-info">
            <strong>
              {startSec !== undefined && endSec !== undefined 
                ? `${Math.floor(startSec)}s - ${Math.floor(endSec)}s` 
                : ''}
            </strong>
            {clipId && <span>Clip ID: {clipId}</span>}
          </div>

          <video 
            controls 
            autoPlay 
            className="moment-video-player"
            onError={() => setVideoError(true)}
          >
            <source src={clipUrl} type="video/mp4" />
            Your browser does not support the video tag.
          </video>

          {videoError && (
            <p className="error">Failed to load video. The clip URL may be expired.</p>
          )}

          <a 
            href={clipUrl} 
            download 
            className="button button-primary"
          >
            Download Clip
          </a>
        </div>
      </section>
    </DashboardLayout>
  )
}

export default MomentClipViewer