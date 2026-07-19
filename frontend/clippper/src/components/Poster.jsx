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
function Poster({
  boxed = false,
  caption,
  format = '9:16',
  isTop = false,
  onClick,
  score,
  showFormat = true,
}) {
  const Tag = onClick ? 'button' : 'div'
  const classes = ['poster', boxed ? 'is-boxed' : '', shapeClass[format] || '']

  return (
    <Tag
      className={classes.filter(Boolean).join(' ')}
      onClick={onClick}
      type={onClick ? 'button' : undefined}
      aria-label={onClick ? `Open ${caption || 'this clip'}` : undefined}
    >
      {/* The frame is the clip itself. Boxed, it keeps its own shape inside a
          tile that is always the same height, so a wide clip no longer makes a
          short tile in a row of tall ones. */}
      <span className="poster-frame">
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
      </span>
    </Tag>
  )
}

export default Poster
