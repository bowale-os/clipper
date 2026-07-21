import { useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useUser } from '@clerk/react'
import TopBar from '../components/TopBar'
import DropZone from '../components/DropZone'
import GlideSearch from '../components/GlideSearch'
import LiveStatus from '../components/LiveStatus'
import EmptyState from '../components/EmptyState'
import DeleteVideo from '../components/DeleteVideo'
import { ScissorsIcon } from '../components/icons'
import { useUserVideos } from '../hooks/useUserVideos'
import { useDeleteVideo } from '../hooks/useDeleteVideo'
import { flattenVideos } from '../lib/videos'
import { getVideoId, formatDate } from '../lib/format'

const REFRESH_MS = 15000
const WORKING = ['uploading', 'uploaded', 'processing']

function greeting(date = new Date()) {
  const hour = date.getHours()

  if (hour < 12) {
    return 'Morning'
  }

  if (hour < 18) {
    return 'Afternoon'
  }

  return 'Evening'
}

function readyLine(video) {
  const count = Number(video?.clip_count) || 0
  const clips = count ? `${count} clip${count === 1 ? '' : 's'} ready` : 'Processed'
  const seconds = Number(video?.duration_sec)

  if (Number.isFinite(seconds) && seconds > 0) {
    return `${clips} · ${Math.max(1, Math.round(seconds / 60))} min`
  }

  return clips
}

/**
 * The signed-in landing and the whole launchpad on one scroll: greet, search,
 * drop a new video, see what is still cooking, then every video you have already
 * processed, newest first. Each row opens that video's clips at /v/:id.
 */
function Home() {
  const { user } = useUser()
  const { data, error, isLoading, refresh } = useUserVideos()

  const videos = useMemo(() => flattenVideos(data), [data])
  const readyVideos = useMemo(() => videos.filter((video) => video.status === 'ready'), [videos])
  const workingVideos = useMemo(
    () => videos.filter((video) => WORKING.includes(video.status)),
    [videos],
  )
  const interrupted = useMemo(
    () => videos.find((video) => video.status === 'uploading'),
    [videos],
  )
  const totalClips = useMemo(
    () => readyVideos.reduce((sum, video) => sum + (Number(video.clip_count) || 0), 0),
    [readyVideos],
  )

  const remove = useDeleteVideo({ onDeleted: () => refresh({ markLoading: false }) })

  // Keep the list warm while anything is still processing, with no refresh button.
  useEffect(() => {
    if (!workingVideos.length) {
      return
    }

    const intervalId = window.setInterval(() => refresh({ markLoading: false }), REFRESH_MS)
    return () => window.clearInterval(intervalId)
  }, [workingVideos.length, refresh])

  const hasAnything = videos.length > 0

  // First visit: greet, explain, and give the drop zone the whole room.
  if (!isLoading && !hasAnything) {
    return (
      <div className="app-shell">
        <div className="app-content">
          <TopBar />

          <div className="welcome">
            <h1>Welcome{user?.firstName ? `, ${user.firstName}` : ''}. Let's get your first clips.</h1>
            <p>
              Drop in a video and we will watch the whole thing for you, then hand back the bits
              worth posting.
            </p>
          </div>

          <DropZone large onUploaded={() => refresh({ markLoading: false })} />

          <ol className="steps">
            <li>
              <span>
                <b>You upload.</b> A video, a recording, anything long.
              </span>
            </li>
            <li>
              <span>
                <b>We watch all of it.</b> Every minute, so you don't have to.
              </span>
            </li>
            <li>
              <span>
                <b>You get clips.</b> Ready to post, with captions already on.
              </span>
            </li>
          </ol>

          {error ? (
            <p className="message error" style={{ marginTop: 'var(--space-6)' }}>
              {error}
            </p>
          ) : null}
        </div>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <div className="app-content">
        <TopBar />

        <p className="greet">
          {greeting()}
          {user?.firstName ? (
            <>
              , <b>{user.firstName}</b>
            </>
          ) : null}
          .{' '}
          {totalClips
            ? `${totalClips} ${totalClips === 1 ? 'clip is' : 'clips are'} ready.`
            : workingVideos.length
              ? 'We are still watching your video.'
              : 'Drop a video to get started.'}
        </p>

        <GlideSearch videos={videos} />

        <div className="home-drop">
          <DropZone
            onUploaded={() => refresh({ markLoading: false })}
            resumeTarget={
              interrupted
                ? {
                    videoId: getVideoId(interrupted),
                    filename: interrupted.filename,
                    sizeBytes: interrupted.size_bytes ?? interrupted.size,
                  }
                : null
            }
          />
        </div>

        {error ? (
          <p className="message error" style={{ marginTop: 'var(--space-4)' }}>
            {error}
          </p>
        ) : null}

        {workingVideos.length ? (
          <>
            <div className="section-head">
              <h2>Working on it</h2>
            </div>
            <div className="processing-list">
              {workingVideos.map((video) => {
                const id = getVideoId(video)

                return (
                  <div className="processing-row" key={id}>
                    <span className="processing-thumb" />
                    <div className="processing-body">
                      <b>{video.filename || 'Your video'}</b>
                      <div className="progress-track is-indeterminate">
                        <span />
                      </div>
                    </div>
                    <LiveStatus status={video.retrying ? 'waiting' : video.status} />
                    <DeleteVideo
                      error={remove.error}
                      filename={video.filename}
                      isDeleting={remove.deletingId === id}
                      isPending={remove.pendingId === id}
                      onAsk={() => remove.ask(id)}
                      onCancel={remove.cancel}
                      onConfirm={() => remove.confirm(id)}
                    />
                  </div>
                )
              })}
            </div>
          </>
        ) : null}

        {readyVideos.length ? (
          <>
            <div className="section-head">
              <h2>Your videos</h2>
              <span className="section-note">{readyVideos.length} processed</span>
            </div>
            <div className="ledger">
              {readyVideos.map((video, index) => {
                const id = getVideoId(video)

                return (
                  <Link className="ledger-row" key={id} to={`/v/${encodeURIComponent(id)}`}>
                    <span className="ledger-idx">{String(index + 1).padStart(2, '0')}</span>
                    <span className="ledger-main">
                      <span className="ledger-title">{video.filename || 'Untitled video'}</span>
                      <span className="ledger-sub">{readyLine(video)}</span>
                    </span>
                    <span className="ledger-date">
                      {formatDate(video.created_at)}
                      <span className="ledger-arrow" aria-hidden="true">
                        →
                      </span>
                    </span>
                  </Link>
                )
              })}
            </div>
          </>
        ) : !workingVideos.length && !isLoading ? (
          <EmptyState
            description="Drop a video above and your clips will start showing up here."
            glyph={<ScissorsIcon size={22} />}
            roomy
            title="No videos yet"
          />
        ) : null}
      </div>
    </div>
  )
}

export default Home
