import DashboardLayout from '../components/DashboardLayout'
import { useUserVideos } from '../hooks/useUserVideos'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { ApiError, deleteVideo } from '../services/api'
import { useAuthedApi } from '../hooks/useAuthedApi'

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

function getReadableError(error) {
  if (error instanceof ApiError) {
    return error.status ? `${error.message} (${error.status})` : error.message
  }

  if (error instanceof Error) {
    return error.message
  }

  return 'Video could not be deleted.'
}

function VideoTable({ deletingVideoId, emptyLabel, onDeleteVideo, title, videos }) {
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
            <span role="columnheader">Actions</span>
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
              <span className="video-actions" role="cell">
                {video.status === 'analyzed' ? (
                  <Link
                    className="button button-primary"
                    to={`/videos/${encodeURIComponent(getVideoId(video))}/moments`}
                  >
                    Show moments
                  </Link>
                ) : null}
                {['uploaded', 'analyzed'].includes(video.status) ? (
                  <Link
                    className="button button-secondary"
                    to={`/videos/${encodeURIComponent(getVideoId(video))}/clips`}
                  >
                    Cut clip
                  </Link>
                ) : null}
                <button
                  className="button button-danger"
                  type="button"
                  onClick={() => onDeleteVideo(video)}
                  disabled={deletingVideoId === getVideoId(video)}
                >
                  {deletingVideoId === getVideoId(video) ? 'Deleting...' : 'Delete'}
                </button>
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

function VideoCountSummary({ counts }) {
  return (
    <section className="video-count-summary" aria-label="Video category counts">
      {counts.map((count) => (
        <article key={count.label}>
          <span>{count.value}</span>
          <p>{count.label}</p>
        </article>
      ))}
    </section>
  )
}

function Videos() {
  const { data, error, isLoading, refresh } = useUserVideos()
  const { runWithToken } = useAuthedApi()
  const [deleteError, setDeleteError] = useState('')
  const [deletingVideoId, setDeletingVideoId] = useState('')
  const uploadedVideos = asArray(data?.uploaded_videos)
  const uploadingVideos = asArray(data?.uploading_videos)
  const processingVideos = asArray(data?.processing_videos)
  const analyzedVideos = asArray(data?.analyzed_videos)
  const errorVideos = asArray(data?.error_videos)

  async function handleDeleteVideo(video) {
    const videoId = getVideoId(video)

    if (!videoId || videoId === 'Unknown ID') {
      setDeleteError('Video ID is missing.')
      return
    }

    const shouldDelete = window.confirm(`Delete "${video.filename || videoId}"? This also deletes its stored video file.`)
    if (!shouldDelete) {
      return
    }

    try {
      setDeleteError('')
      setDeletingVideoId(videoId)
      await runWithToken((token) => deleteVideo({ token, videoId }))
      await refresh({ markLoading: false })
    } catch (deleteFailure) {
      setDeleteError(getReadableError(deleteFailure))
    } finally {
      setDeletingVideoId('')
    }
  }

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

        {deleteError ? (
          <div className="upload-message error">
            {deleteError}
          </div>
        ) : null}

        {isLoading ? (
          <div className="dashboard-panel videos-loading">Loading videos...</div>
        ) : (
          <>
            <VideoCountSummary
              counts={[
                { label: 'Analyzed', value: analyzedVideos.length },
                { label: 'Processing', value: processingVideos.length },
                { label: 'Errors', value: errorVideos.length },
                { label: 'Uploading', value: uploadingVideos.length },
                { label: 'Uploaded', value: uploadedVideos.length },
              ]}
            />
            <VideoTable
              deletingVideoId={deletingVideoId}
              emptyLabel="No analyzed videos yet."
              onDeleteVideo={handleDeleteVideo}
              title="Analyzed videos"
              videos={analyzedVideos}
            />
            <VideoTable
              deletingVideoId={deletingVideoId}
              emptyLabel="No videos currently processing."
              onDeleteVideo={handleDeleteVideo}
              title="Processing videos"
              videos={processingVideos}
            />
            <VideoTable
              deletingVideoId={deletingVideoId}
              emptyLabel="No videos with errors."
              onDeleteVideo={handleDeleteVideo}
              title="Error videos"
              videos={errorVideos}
            />
            <VideoTable
              deletingVideoId={deletingVideoId}
              emptyLabel="No videos currently uploading."
              onDeleteVideo={handleDeleteVideo}
              title="Uploading videos"
              videos={uploadingVideos}
            />
            <VideoTable
              deletingVideoId={deletingVideoId}
              emptyLabel="No completed uploads yet."
              onDeleteVideo={handleDeleteVideo}
              title="Uploaded videos"
              videos={uploadedVideos}
            />
          </>
        )}
      </section>
    </DashboardLayout>
  )
}

export default Videos
