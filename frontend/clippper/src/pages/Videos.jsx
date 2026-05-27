import DashboardLayout from '../components/DashboardLayout'
import { useUserVideos } from '../hooks/useUserVideos'

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function formatBytes(bytes) {
  if (!bytes) {
    return 'Unknown size'
  }

  const units = ['B', 'KB', 'MB', 'GB']
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** exponent

  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`
}

function formatDate(value) {
  if (!value) {
    return 'No date'
  }

  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return String(value)
  }

  return date.toLocaleString()
}

function getVideoId(video) {
  return video?._id || video?.id || video?.video_id || 'Unknown ID'
}

function VideoTable({ emptyLabel, title, videos }) {
  return (
    <section className="dashboard-panel videos-panel">
      <div className="panel-heading">
        <div>
          <p className="panel-label">{videos.length} videos</p>
          <h2>{title}</h2>
        </div>
      </div>

      {videos.length ? (
        <div className="videos-table" role="table" aria-label={title}>
          <div className="videos-table-row videos-table-head" role="row">
            <span role="columnheader">File</span>
            <span role="columnheader">Status</span>
            <span role="columnheader">Size</span>
            <span role="columnheader">Created</span>
            <span role="columnheader">Video ID</span>
          </div>
          {videos.map((video) => (
            <div className="videos-table-row" role="row" key={getVideoId(video)}>
              <span role="cell">
                <strong>{video.filename || 'Untitled video'}</strong>
              </span>
              <span role="cell">
                <mark>{video.status || 'unknown'}</mark>
              </span>
              <span role="cell">{formatBytes(video.size)}</span>
              <span role="cell">{formatDate(video.created_at)}</span>
              <span className="video-id" role="cell">
                {getVideoId(video)}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="videos-empty">
          <strong>{emptyLabel}</strong>
          <span>Upload a video from the dashboard, then refresh this page.</span>
        </div>
      )}
    </section>
  )
}

function Videos() {
  const { data, error, isLoading, refresh } = useUserVideos()
  const uploadedVideos = asArray(data?.uploaded_videos)
  const uploadingVideos = asArray(data?.uploading_videos)

  return (
    <DashboardLayout eyebrow="Debug workspace" title="Videos uploaded by this user.">
      <section className="videos-page">
        <div className="videos-toolbar">
          <div>
            <p className="panel-label">Backend source</p>
            <h2>GET /videos/</h2>
          </div>
          <button className="button button-secondary" type="button" onClick={refresh} disabled={isLoading}>
            {isLoading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>

        {error ? (
          <div className="upload-message error">
            {error}
          </div>
        ) : null}

        {isLoading ? (
          <div className="dashboard-panel videos-loading">Loading videos...</div>
        ) : (
          <>
            <VideoTable
              emptyLabel="No completed uploads yet."
              title="Uploaded videos"
              videos={uploadedVideos}
            />
            <VideoTable
              emptyLabel="No videos currently uploading."
              title="Uploading videos"
              videos={uploadingVideos}
            />
          </>
        )}
      </section>
    </DashboardLayout>
  )
}

export default Videos
