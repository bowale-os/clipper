import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useUser } from '@clerk/react'
import TopBar from '../components/TopBar'
import DropZone from '../components/DropZone'
import ClipTile from '../components/ClipTile'
import ClipPreview from '../components/ClipPreview'
import LiveStatus from '../components/LiveStatus'
import EmptyState from '../components/EmptyState'
import { ScissorsIcon } from '../components/icons'
import { useUserVideos } from '../hooks/useUserVideos'
import { useVideoMoments } from '../hooks/useVideoMoments'
import { useClipRenders, getMomentKey } from '../hooks/useClipRenders'
import { usePrefs } from '../hooks/usePrefs'
import { flattenVideos } from '../lib/videos'
import { getVideoId } from '../lib/format'

const REFRESH_MS = 15000

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

function isWorking(video) {
  return ['uploaded', 'processing'].includes(video?.status)
}

/**
 * The whole signed-in app. There is no dashboard and no separate welcome page —
 * this one screen greets you on the first visit and then gets out of the way,
 * handing the space to your clips.
 */
function Studio() {
  const { user } = useUser()
  const { prefs } = usePrefs()
  const { data, error, isLoading, refresh } = useUserVideos()
  const { renders, start } = useClipRenders()

  const [selectedVideoId, setSelectedVideoId] = useState('')
  const [openMoment, setOpenMoment] = useState(null)

  const videos = useMemo(() => flattenVideos(data), [data])
  const readyVideos = useMemo(() => videos.filter((video) => video.status === 'ready'), [videos])
  const workingVideos = useMemo(() => videos.filter(isWorking), [videos])
  const interrupted = useMemo(() => videos.find((video) => video.status === 'uploading'), [videos])

  // Default to the newest analyzed stream, but never fight a pick the user made.
  const activeVideo =
    readyVideos.find((video) => getVideoId(video) === selectedVideoId) || readyVideos[0] || null
  const activeVideoId = getVideoId(activeVideo)

  const {
    data: momentsData,
    error: momentsError,
    isLoading: isMomentsLoading,
  } = useVideoMoments(activeVideoId)

  const moments = momentsData?.moments || []

  // Something is still cooking, so keep the list warm without a refresh button.
  useEffect(() => {
    if (!workingVideos.length) {
      return
    }

    const intervalId = window.setInterval(() => refresh({ markLoading: false }), REFRESH_MS)
    return () => window.clearInterval(intervalId)
  }, [workingVideos.length, refresh])

  const handleRender = useCallback(
    ({ moment, format, autoDownload = false }) => {
      start({
        autoDownload,
        captions: prefs.captions,
        format: format || prefs.format,
        moment,
        videoId: activeVideoId,
      })
    },
    [activeVideoId, prefs.captions, prefs.format, start],
  )

  const handleDownload = useCallback(
    (moment) => handleRender({ moment, autoDownload: true }),
    [handleRender],
  )

  const hasAnything = videos.length > 0
  const openKey = openMoment ? getMomentKey(openMoment, activeVideoId) : ''

  // First visit: greet, explain, and give the drop zone the room.
  if (!isLoading && !hasAnything) {
    return (
      <div className="app-shell">
        <div className="app-content">
          <TopBar />

          <div className="welcome">
            <h1>Welcome{user?.firstName ? `, ${user.firstName}` : ''}. Let's get your first clips.</h1>
            <p>
              Drop in a stream and we will watch the whole thing for you, then hand back the bits
              worth posting.
            </p>
          </div>

          <DropZone large onUploaded={() => refresh({ markLoading: false })} />

          <ol className="steps">
            <li>
              <span>
                <b>You upload.</b> A stream, a recording, anything long.
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

          {error ? <p className="message error" style={{ marginTop: 'var(--space-6)' }}>{error}</p> : null}
        </div>
      </div>
    )
  }

  const readyCount = moments.length

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
          {readyCount
            ? `${readyCount} ${readyCount === 1 ? 'clip is' : 'clips are'} ready.`
            : workingVideos.length
              ? 'We are still watching your stream.'
              : 'Drop in a stream to get started.'}
        </p>

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

        {error ? <p className="message error" style={{ marginTop: 'var(--space-4)' }}>{error}</p> : null}

        {workingVideos.length ? (
          <>
            <div className="section-head">
              <h2>Working on it</h2>
            </div>
            <div className="processing-list">
              {workingVideos.map((video) => (
                <div className="processing-row" key={getVideoId(video)}>
                  <span className="processing-thumb" />
                  <div className="processing-body">
                    <b>{video.filename || 'Your stream'}</b>
                    <div className="progress-track is-indeterminate">
                      <span />
                    </div>
                  </div>
                  <LiveStatus status={video.status} />
                </div>
              ))}
            </div>
          </>
        ) : null}

        {readyVideos.length > 1 ? (
          <>
            <div className="section-head">
              <h2>Your streams</h2>
            </div>
            <div className="chip-row stream-filter">
              {readyVideos.map((video) => {
                const id = getVideoId(video)
                return (
                  <button
                    aria-pressed={id === activeVideoId}
                    className="chip"
                    key={id}
                    onClick={() => setSelectedVideoId(id)}
                    type="button"
                  >
                    <span className="chip-label">{video.filename || 'Untitled'}</span>
                  </button>
                )
              })}
            </div>
          </>
        ) : null}

        {activeVideo ? (
          <>
            <div className="section-head">
              <h2>
                Ready · <b>{activeVideo.filename || 'Untitled'}</b>
              </h2>
              <Link className="section-link" to={`/trim/${encodeURIComponent(activeVideoId)}`}>
                Cut your own
              </Link>
            </div>

            {momentsError ? <p className="message error">{momentsError}</p> : null}

            {isMomentsLoading ? (
              <div className="clip-grid">
                {Array.from({ length: 4 }, (_, index) => (
                  <div className="skeleton skeleton-tile" key={index} />
                ))}
              </div>
            ) : moments.length ? (
              <div className="clip-grid">
                {moments.map((moment, index) => (
                  <ClipTile
                    format={renders[getMomentKey(moment, activeVideoId)]?.format || prefs.format}
                    isTop={index === 0}
                    key={getMomentKey(moment, activeVideoId)}
                    moment={moment}
                    onDownload={handleDownload}
                    onOpen={setOpenMoment}
                    render={renders[getMomentKey(moment, activeVideoId)]}
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                description="We got through this one but nothing stood out. A longer stream usually gives us more to work with, or you can cut a bit yourself."
                glyph={<ScissorsIcon size={22} />}
                title="Nothing worth posting in this one"
              />
            )}
          </>
        ) : !workingVideos.length && !isLoading ? (
          <EmptyState
            description="Drop a stream above and your clips will start showing up here."
            glyph={<ScissorsIcon size={22} />}
            title="No clips yet"
          />
        ) : null}
      </div>

      {openMoment ? (
        <ClipPreview
          format={prefs.format}
          moment={openMoment}
          onClose={() => setOpenMoment(null)}
          onRender={handleRender}
          render={renders[openKey]}
        />
      ) : null}
    </div>
  )
}

export default Studio
