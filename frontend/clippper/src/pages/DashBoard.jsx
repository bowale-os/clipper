import { useMemo, useRef } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import VideoUploadCard from '../components/VideoUploadCard'
import VideoCard from '../components/VideoCard'
import EmptyState from '../components/EmptyState'
import { ScissorsIcon, UploadIcon } from '../components/icons'
import { useUserVideos } from '../hooks/useUserVideos'
import { flattenVideos } from '../lib/videos'
import { getVideoId } from '../lib/format'

const RECENT_LIMIT = 4

function DashBoard() {
  // The videos list navigates here with a resume target for interrupted uploads.
  const location = useLocation()
  const navigate = useNavigate()
  const resumeTarget = location.state?.resume || null
  const uploadRef = useRef(null)

  const { data, error, isLoading } = useUserVideos()
  const videos = useMemo(() => flattenVideos(data), [data])
  const latestReady = videos.find((video) => video.status === 'ready')
  const recentVideos = videos.slice(0, RECENT_LIMIT)

  function scrollToUpload() {
    uploadRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function handleResumeVideo(video) {
    navigate('/dashboard', {
      state: {
        resume: {
          videoId: getVideoId(video),
          filename: video.filename,
          sizeBytes: video.size_bytes ?? video.size,
        },
      },
    })
  }

  return (
    <AppLayout eyebrow="Dashboard" title="What do you want to do?">
      <div className="action-grid">
        <Link
          className="action-card"
          to={latestReady ? `/videos/${encodeURIComponent(getVideoId(latestReady))}/moments` : '#'}
          onClick={(event) => {
            if (!latestReady) {
              event.preventDefault()
              scrollToUpload()
            }
          }}
          aria-disabled={!latestReady}
        >
          <span className="action-card-glyph">
            <ScissorsIcon size={20} />
          </span>
          <h2>Clip my latest stream</h2>
          <p>
            {latestReady
              ? `Jump straight to the best moments in ${latestReady.filename || 'your newest video'}.`
              : 'Nothing analyzed yet — upload a stream and this lights up.'}
          </p>
        </Link>

        <button className="action-card" onClick={scrollToUpload} type="button">
          <span className="action-card-glyph">
            <UploadIcon size={20} />
          </span>
          <h2>Upload a video</h2>
          <p>Drop in a long stream or VOD. We'll find the moments while you get on with your day.</p>
        </button>
      </div>

      <section className="upload-layout" ref={uploadRef}>
        <VideoUploadCard key={resumeTarget?.videoId || 'fresh'} resumeTarget={resumeTarget} />

        <aside className="card">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">How it works</p>
              <h2>Set it and forget it</h2>
            </div>
          </div>
          <ol className="upload-steps">
            <li>
              <div>
                <strong>Upload</strong>
                <span>Your browser sends the file straight to storage.</span>
              </div>
            </li>
            <li>
              <div>
                <strong>We watch it for you</strong>
                <span>Transcribe, then score every moment for hook and shareability.</span>
              </div>
            </li>
            <li>
              <div>
                <strong>Pick your winners</strong>
                <span>Review ranked moments and generate the ones you like.</span>
              </div>
            </li>
            <li>
              <div>
                <strong>Post</strong>
                <span>Download ready-to-post clips with captions burned in.</span>
              </div>
            </li>
          </ol>
        </aside>
      </section>

      <section className="dashboard-section">
        <div className="dashboard-section-head">
          <h2>Recent uploads</h2>
          <Link className="button button-secondary" to="/videos">
            View library
          </Link>
        </div>

        {error ? <p className="message error">{error}</p> : null}

        {isLoading ? (
          <div className="card-grid">
            {Array.from({ length: RECENT_LIMIT }, (_, index) => (
              <div className="skeleton skeleton-card" key={index} />
            ))}
          </div>
        ) : recentVideos.length ? (
          <div className="card-grid">
            {/* Deleting lives in the library, so these cards are read-plus-act only. */}
            {recentVideos.map((video) => (
              <VideoCard key={getVideoId(video)} onResume={handleResumeVideo} video={video} />
            ))}
          </div>
        ) : (
          <EmptyState
            description="Upload your first stream above and your clips will start showing up here."
            title="No uploads yet"
          />
        )}
      </section>
    </AppLayout>
  )
}

export default DashBoard
