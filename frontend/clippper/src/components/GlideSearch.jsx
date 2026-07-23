import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useVideoSearch } from '../hooks/useVideoSearch'
import { getVideoId, formatDate } from '../lib/format'
import { SearchIcon } from './icons'

const RECENT_LIMIT = 6

const SHORTCUT =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || '')
    ? '⌘K'
    : 'Ctrl K'

function clipLabel(video) {
  const count = Number(video?.clip_count) || 0
  return `${count} clip${count === 1 ? '' : 's'}`
}

/**
 * The one search box. It matches videos by name and lands you on that video's
 * clips. Two shapes of the same thing:
 *  - variant="inline": lives in the page and glides up to dock when opened. Home.
 *  - variant="overlay": a pill that drops a floating panel in. Anywhere else.
 * Either way ⌘K / Ctrl-K opens it and Esc closes it.
 */
function GlideSearch({ videos = [], variant = 'inline' }) {
  const navigate = useNavigate()
  const inputRef = useRef(null)
  const [open, setOpen] = useState(false)
  const [closing, setClosing] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)

  const recents = useMemo(
    () => videos.filter((video) => video?.status === 'ready').slice(0, RECENT_LIMIT),
    [videos],
  )
  const { results, isSearching } = useVideoSearch(query, videos)

  const hasQuery = Boolean(query.trim())
  const shown = hasQuery ? results : recents

  const close = useCallback(() => {
    // Overlay plays an exit animation, so keep it mounted until the motion ends.
    // Inline has no exit beat and can just snap shut.
    if (variant === 'overlay') {
      setClosing(true)
      window.setTimeout(() => {
        setOpen(false)
        setClosing(false)
        setQuery('')
        setActive(0)
      }, 500)
      return
    }
    setOpen(false)
    setQuery('')
    setActive(0)
  }, [variant])

  const go = useCallback(
    (video) => {
      const id = getVideoId(video)
      if (!id) {
        return
      }
      close()
      navigate(`/v/${encodeURIComponent(id)}`)
    },
    [close, navigate],
  )

  // ⌘K / Ctrl-K opens from anywhere; Esc always closes.
  useEffect(() => {
    function onKey(event) {
      if ((event.metaKey || event.ctrlKey) && (event.key === 'k' || event.key === 'K')) {
        event.preventDefault()
        setOpen(true)
      } else if (event.key === 'Escape') {
        close()
      }
    }

    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [close])

  // Focus the input once it exists. Inline waits for the glide so the caret does
  // not jump ahead of the motion.
  useEffect(() => {
    if (!open) {
      return
    }
    const delay = variant === 'inline' ? 260 : 40
    const timeoutId = window.setTimeout(() => inputRef.current?.focus(), delay)
    return () => window.clearTimeout(timeoutId)
  }, [open, variant])

  // A new query changes the list under the cursor, so start from the top.
  const onQueryChange = (event) => {
    setQuery(event.target.value)
    setActive(0)
  }

  const onInputKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((index) => Math.min(index + 1, shown.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (shown[active]) {
        go(shown[active])
      }
    }
  }

  const label = hasQuery
    ? isSearching
      ? 'Searching…'
      : `${results.length} video${results.length === 1 ? '' : 's'} match`
    : 'Recent videos'

  const results_ui = (
    <div className="glide-panel-inner">
      <div className="glide-label">{label}</div>
      {shown.length ? (
        shown.map((video, index) => (
          <button
            className={`glide-row${index === active ? ' is-active' : ''}`}
            key={getVideoId(video)}
            onClick={() => go(video)}
            onMouseEnter={() => setActive(index)}
            tabIndex={open ? 0 : -1}
            type="button"
          >
            <span className="glide-thumb" />
            <span className="glide-row-name">{video.filename || 'Untitled video'}</span>
            <span className="glide-row-meta">
              {clipLabel(video)} &middot; {formatDate(video.created_at)}
            </span>
          </button>
        ))
      ) : (
        <div className="glide-empty">
          {hasQuery
            ? `No videos match "${query.trim()}".`
            : 'Your processed videos will show up here.'}
        </div>
      )}
      <div className="glide-foot">
        <span>
          <kbd>&uarr;</kbd>
          <kbd>&darr;</kbd> move
        </span>
        <span>
          <kbd>&crarr;</kbd> open clips
        </span>
        <span>
          <kbd>esc</kbd> close
        </span>
      </div>
    </div>
  )

  if (variant === 'overlay') {
    return (
      <>
        <button
          aria-label="Search your videos"
          className="glide-pill"
          onClick={() => setOpen(true)}
          type="button"
        >
          <SearchIcon size={15} />
          <span>Search</span>
          <span className="glide-k">{SHORTCUT}</span>
        </button>

        {open ? (
          <div
            className={`glide-overlay${closing ? ' is-closing' : ''}`}
            role="dialog"
            aria-modal="true"
            aria-label="Search your videos"
          >
            <div className="glide-scrim is-static" onClick={close} />
            <div className="glide-float">
              <div className="glide-bar">
                <SearchIcon size={18} />
                <input
                  className="glide-input"
                  onChange={onQueryChange}
                  onKeyDown={onInputKeyDown}
                  placeholder="Search your videos by name"
                  ref={inputRef}
                  value={query}
                />
                <button className="glide-esc" onClick={close} type="button">
                  esc
                </button>
              </div>
              <div className="glide-panel is-float">{results_ui}</div>
            </div>
          </div>
        ) : null}
      </>
    )
  }

  return (
    <div className={`glide-search${open ? ' is-open' : ''}`}>
      <div className="glide-scrim" onClick={close} />
      <div className="glide-wrap">
        <div
          className="glide-bar"
          onClick={() => setOpen(true)}
          onKeyDown={(event) => {
            if (!open && (event.key === 'Enter' || event.key === ' ')) {
              event.preventDefault()
              setOpen(true)
            }
          }}
          role={open ? undefined : 'button'}
          tabIndex={open ? -1 : 0}
        >
          <SearchIcon size={17} />
          {open ? (
            <input
              className="glide-input"
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onInputKeyDown}
              placeholder="Search your videos by name"
              ref={inputRef}
              value={query}
            />
          ) : (
            <span className="glide-ph">Search your videos by name</span>
          )}
          {open ? (
            <button className="glide-esc" onClick={close} type="button">
              esc
            </button>
          ) : (
            <span className="glide-k">{SHORTCUT}</span>
          )}
        </div>
        <div className="glide-panel">{results_ui}</div>
      </div>
    </div>
  )
}

export default GlideSearch
