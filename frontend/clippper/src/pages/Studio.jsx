import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import TopBar from '../components/TopBar'
import GlideSearch from '../components/GlideSearch'
import ClipTile from '../components/ClipTile'
import ClipPreview from '../components/ClipPreview'
import LiveStatus from '../components/LiveStatus'
import EmptyState from '../components/EmptyState'
import DeleteVideo from '../components/DeleteVideo'
import MomentSort from '../components/MomentSort'
import { ArrowLeftIcon, ScissorsIcon } from '../components/icons'
import { useUserVideos } from '../hooks/useUserVideos'
import { useVideoMoments } from '../hooks/useVideoMoments'
import { useVideoClips } from '../hooks/useVideoClips'
import { useDeleteVideo } from '../hooks/useDeleteVideo'
import { useClipRenders, getMomentKey } from '../hooks/useClipRenders'
import { usePrefs } from '../hooks/usePrefs'
import { flattenVideos } from '../lib/videos'
import { getVideoId } from '../lib/format'
import { DEFAULT_MOMENT_SORT, MOMENT_SORTS, sortMoments } from '../lib/moments'

const REFRESH_MS = 15000
const WORKING = ['uploading', 'uploaded', 'processing']

/**
 * One video, at its own address. Resolves the video from the shared list, then
 * parks the moments/clips hooks until it is ready so a processing or missing id
 * never fires a doomed request. Everything about a finished video — the clips
 * grid, the preview, "Cut your own", delete — lives here.
 */
function Studio() {
  const { videoId } = useParams()
  const navigate = useNavigate()
  const { prefs } = usePrefs()
  const { data, isLoading: isListLoading, refresh } = useUserVideos()
  const { renders, start, seed } = useClipRenders()

  const [openMoment, setOpenMoment] = useState(null)

  // The chosen order is stored against the video it was chosen for. Reading it back only
  // when the stored video matches the one on screen means every video opens on the overall
  // score without an effect resetting anything — the sort is a look you take on one video,
  // not a setting that follows you around and later reads as a wrong ranking.
  const [sortChoice, setSortChoice] = useState({ videoId, key: DEFAULT_MOMENT_SORT })
  const sort = sortChoice.videoId === videoId ? sortChoice.key : DEFAULT_MOMENT_SORT
  const setSort = useCallback((key) => setSortChoice({ videoId, key }), [videoId])

  const videos = useMemo(() => flattenVideos(data), [data])
  const video = useMemo(
    () => videos.find((item) => getVideoId(item) === videoId) || null,
    [videos, videoId],
  )
  const status = video?.status
  const isReady = status === 'ready'
  const isWorking = WORKING.includes(status)
  const notFound = !isListLoading && !video

  const remove = useDeleteVideo({
    onDeleted: () => navigate('/', { replace: true }),
  })

  const {
    data: momentsData,
    error: momentsError,
    isLoading: isMomentsLoading,
  } = useVideoMoments(isReady ? videoId : '')

  const { clips: serverClips } = useVideoClips(isReady ? videoId : '')

  const rawMoments = useMemo(() => momentsData?.moments || [], [momentsData])
  const moments = useMemo(() => sortMoments(rawMoments, sort), [rawMoments, sort])
  const activeSort = MOMENT_SORTS.find((option) => option.key === sort) || MOMENT_SORTS[0]

  // Each clip's 1-based rank in the overall-score order — the view every video opens on.
  // When another order is showing, a tile whose rank here differs shows "was Nth", which is
  // the proof the two orders actually disagree instead of a reorder that changed nothing.
  // Pure from the data, so it just falls out correct as clips finish rendering and arrive.
  const overallRank = useMemo(() => {
    const byScore = sortMoments(rawMoments, DEFAULT_MOMENT_SORT)
    return new Map(byScore.map((moment, index) => [moment.id, index + 1]))
  }, [rawMoments])

  // Hand the already-rendered clips to the render store, keyed the way the tiles
  // are, so a clip detect finished on its own shows as ready straight away.
  useEffect(() => {
    if (!serverClips.length || !moments.length) {
      return
    }

    const byId = new Map(moments.map((moment) => [moment.id, moment]))
    const entries = serverClips
      .filter((clip) => byId.has(clip.moment_id))
      .map((clip) => {
        const moment = byId.get(clip.moment_id)

        return {
          captions: clip.captions,
          clipId: clip.clip_id,
          format: clip.format,
          key: getMomentKey(moment, videoId),
          moment,
          status: clip.status,
          url: clip.url,
        }
      })

    if (entries.length) {
      seed(entries)
    }
  }, [videoId, moments, seed, serverClips])

  // Tiles you can actually watch. Two things this has to get right: a clip row is not
  // a clip until it has a file, and a moment can own more than one clip row, because
  // re-rendering it with captions or another shape adds a row rather than replacing
  // one. Counting rows would say "13 of 12 ready" as soon as someone re-cuts a tile.
  const readyCount = useMemo(() => {
    const readyMoments = new Set(
      serverClips
        .filter((clip) => clip.status === 'ready' && clip.url && clip.moment_id)
        .map((clip) => clip.moment_id),
    )
    return moments.filter((moment) => readyMoments.has(moment.id)).length
  }, [moments, serverClips])

  // Still processing: keep the list warm so the page flips to ready on its own.
  useEffect(() => {
    if (!isWorking) {
      return
    }

    const intervalId = window.setInterval(() => refresh({ markLoading: false }), REFRESH_MS)
    return () => window.clearInterval(intervalId)
  }, [isWorking, refresh])

  const handleRender = useCallback(
    ({ moment, format, captions, autoDownload = false }) => {
      const existing = renders[getMomentKey(moment, videoId)]
      const settled = existing?.status === 'ready' && existing.url

      start({
        autoDownload,
        captions:
          typeof captions === 'boolean'
            ? captions
            : settled && !format
              ? existing.captions
              : prefs.captions,
        format: format || (settled ? existing.format : prefs.format),
        moment,
        videoId,
      })
    },
    [videoId, prefs.captions, prefs.format, renders, start],
  )

  const handleDownload = useCallback(
    (moment) => handleRender({ moment, autoDownload: true }),
    [handleRender],
  )

  const openKey = openMoment ? getMomentKey(openMoment, videoId) : ''
  const search = <GlideSearch variant="overlay" videos={videos} />

  function renderBody() {
    if (notFound) {
      return (
        <EmptyState
          description="This video may have been deleted, or the link is wrong. Head back home to pick another."
          glyph={<ScissorsIcon size={22} />}
          roomy
          title="We can't find that video"
        />
      )
    }

    // List still loading and no match yet — never claim "not found" too early.
    if (!video) {
      return (
        <div className="clip-grid">
          {Array.from({ length: 4 }, (_, index) => (
            <div className="skeleton skeleton-tile" key={index} />
          ))}
        </div>
      )
    }

    if (isWorking) {
      return (
        <div className="processing-list">
          <div className="processing-row">
            <span className="processing-thumb" />
            <div className="processing-body">
              <b>{video.filename || 'Your video'}</b>
              <div className="progress-track is-indeterminate">
                <span />
              </div>
            </div>
            <LiveStatus status={video.retrying ? 'waiting' : video.status} />
          </div>
        </div>
      )
    }

    if (status === 'error') {
      return (
        <p className="message error">
          {video.error || 'Something went wrong watching this one. You can delete it and try again.'}
        </p>
      )
    }

    if (momentsError) {
      return <p className="message error">{momentsError}</p>
    }

    if (isMomentsLoading) {
      return (
        <div className="clip-grid">
          {Array.from({ length: 4 }, (_, index) => (
            <div className="skeleton skeleton-tile" key={index} />
          ))}
        </div>
      )
    }

    if (!moments.length) {
      return (
        <EmptyState
          description="We got through this one but nothing stood out. A longer video usually gives us more to work with, or you can cut a bit yourself."
          glyph={<ScissorsIcon size={22} />}
          title="Nothing worth posting in this one"
        />
      )
    }

    return (
      <>
        <div className="section-head">
          <h2>Your clips</h2>
          <span className="section-note">
            {readyCount === moments.length
              ? readyCount === 1
                ? 'One clip, ready to post.'
                : `All ${readyCount} are ready to post.`
              : `${readyCount} of ${moments.length} ready. The rest are on the way.`}
          </span>
        </div>
        {moments.length > 1 ? (
          <>
            <MomentSort onChange={setSort} value={sort} />
            <p className="sort-note">{activeSort.note}</p>
          </>
        ) : null}
        <div className="clip-grid">
          {moments.map((moment, index) => {
            const rank = overallRank.get(moment.id)
            // Only when a different order is showing, and only if this clip actually sits
            // somewhere other than its overall-score rank.
            const movedFrom =
              sort !== DEFAULT_MOMENT_SORT && rank && rank !== index + 1 ? rank : undefined

            return (
              <ClipTile
                format={renders[getMomentKey(moment, videoId)]?.format || prefs.format}
                isTop={index === 0}
                key={getMomentKey(moment, videoId)}
                moment={moment}
                onDownload={handleDownload}
                onOpen={setOpenMoment}
                previousPlace={movedFrom}
                render={renders[getMomentKey(moment, videoId)]}
                scoreKey={sort}
              />
            )
          })}
        </div>
      </>
    )
  }

  return (
    <div className="app-shell">
      <div className="app-content">
        <TopBar actions={search} />

        <Link className="back-link" to="/">
          <ArrowLeftIcon size={15} />
          Back to home
        </Link>

        {video ? (
          <div className="section-head">
            <h2>
              <b>{video.filename || 'Untitled video'}</b>
            </h2>
            {isReady ? (
              <div className="section-actions">
                <Link className="section-link" to={`/trim/${encodeURIComponent(videoId)}`}>
                  Cut your own
                </Link>
                <DeleteVideo
                  error={remove.error}
                  filename={video.filename}
                  isDeleting={remove.deletingId === videoId}
                  isPending={remove.pendingId === videoId}
                  onAsk={() => remove.ask(videoId)}
                  onCancel={remove.cancel}
                  onConfirm={() => remove.confirm(videoId)}
                />
              </div>
            ) : null}
          </div>
        ) : null}

        {renderBody()}
      </div>

      {openMoment ? (
        <ClipPreview
          captions={prefs.captions}
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
