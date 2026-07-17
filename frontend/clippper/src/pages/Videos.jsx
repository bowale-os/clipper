import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import VideoCard from '../components/VideoCard'
import EmptyState from '../components/EmptyState'
import { FilmIcon } from '../components/icons'
import { useUserVideos } from '../hooks/useUserVideos'
import { useAuthedApi } from '../hooks/useAuthedApi'
import { deleteVideo } from '../services/api'
import { countByStatus, flattenVideos } from '../lib/videos'
import { getVideoId } from '../lib/format'
import { getReadableError } from '../lib/errors'

const filters = [
  { label: 'All', value: 'all' },
  { label: 'Ready', value: 'ready' },
  { label: 'Analyzing', value: 'processing' },
  { label: 'Uploading', value: 'uploading' },
  { label: 'Failed', value: 'error' },
]

// "Analyzing" covers both states between a finished upload and ready moments.
function matchesFilter(video, filter) {
  if (filter === 'all') {
    return true
  }

  if (filter === 'processing') {
    return video.status === 'processing' || video.status === 'uploaded'
  }

  return video.status === filter
}

function Videos() {
  const { data, error, isLoading, refresh } = useUserVideos()
  const { runWithToken } = useAuthedApi()
  const navigate = useNavigate()
  const [deleteError, setDeleteError] = useState('')
  const [deletingVideoId, setDeletingVideoId] = useState('')
  const [filter, setFilter] = useState('all')

  const videos = useMemo(() => flattenVideos(data), [data])
  const counts = useMemo(() => countByStatus(videos), [videos])
  const visibleVideos = useMemo(
    () => videos.filter((video) => matchesFilter(video, filter)),
    [videos, filter],
  )

  function countFor(value) {
    if (value === 'all') {
      return videos.length
    }

    if (value === 'processing') {
      return (counts.processing || 0) + (counts.uploaded || 0)
    }

    return counts[value] || 0
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

  async function handleDeleteVideo(video) {
    const videoId = getVideoId(video)

    if (!videoId) {
      setDeleteError('Video ID is missing.')
      return
    }

    const shouldDelete = window.confirm(
      `Delete "${video.filename || videoId}"? This also deletes its stored video file.`,
    )

    if (!shouldDelete) {
      return
    }

    try {
      setDeleteError('')
      setDeletingVideoId(videoId)
      await runWithToken((token) => deleteVideo({ token, videoId }))
      await refresh({ markLoading: false })
    } catch (deleteFailure) {
      setDeleteError(getReadableError(deleteFailure, 'Video could not be deleted.'))
    } finally {
      setDeletingVideoId('')
    }
  }

  return (
    <AppLayout
      eyebrow="Library"
      title="Everything you've uploaded"
      actions={
        <button className="button button-secondary" type="button" onClick={refresh} disabled={isLoading}>
          {isLoading ? 'Refreshing…' : 'Refresh'}
        </button>
      }
    >
      <div className="library-toolbar">
        <div className="chip-row">
          {filters.map((option) => (
            <button
              aria-pressed={filter === option.value}
              className="chip"
              key={option.value}
              onClick={() => setFilter(option.value)}
              type="button"
            >
              {option.label}
              <span className="chip-count">{countFor(option.value)}</span>
            </button>
          ))}
        </div>
      </div>

      {error ? <p className="message error">{error}</p> : null}
      {deleteError ? <p className="message error">{deleteError}</p> : null}

      {isLoading ? (
        <div className="card-grid">
          {Array.from({ length: 6 }, (_, index) => (
            <div className="skeleton skeleton-card" key={index} />
          ))}
        </div>
      ) : visibleVideos.length ? (
        <div className="card-grid">
          {visibleVideos.map((video) => (
            <VideoCard
              isDeleting={deletingVideoId === getVideoId(video)}
              key={getVideoId(video)}
              onDelete={handleDeleteVideo}
              onResume={handleResumeVideo}
              video={video}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          description={
            videos.length
              ? 'Nothing in this filter yet. Try another one.'
              : "Upload a stream from the dashboard and it'll show up here while we analyze it."
          }
          glyph={<FilmIcon size={22} />}
          title={videos.length ? 'Nothing here' : 'Your library is empty'}
        />
      )}
    </AppLayout>
  )
}

export default Videos
