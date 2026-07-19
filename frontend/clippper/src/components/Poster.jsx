import { PlayIcon } from './icons'

const shapeClass = {
  '9:16': '',
  '1:1': 'is-square',
  '16:9': 'is-wide',
}

/**
 * Stays solid black until the backend can hand back a still frame from the
 * clip. The title sits on it like a burned-in caption so the tile reads as the
 * finished post rather than a row in a list.
 */
function Poster({ caption, format = '9:16', isTop = false, onClick, score, showFormat = true }) {
  const Tag = onClick ? 'button' : 'div'

  return (
    <Tag
      className={`poster ${shapeClass[format] || ''}`.trim()}
      onClick={onClick}
      type={onClick ? 'button' : undefined}
      aria-label={onClick ? `Open ${caption || 'this clip'}` : undefined}
    >
      {score != null ? (
        <span className={isTop ? 'poster-score is-top' : 'poster-score'}>{score}</span>
      ) : null}
      {showFormat ? <span className="poster-format">{format}</span> : null}
      <span className="poster-play">
        <PlayIcon />
      </span>
      {/* title carries the full text, since long ones are clamped to three lines. */}
      {caption ? (
        <span className="poster-caption" title={caption}>
          {caption}
        </span>
      ) : null}
    </Tag>
  )
}

export default Poster
