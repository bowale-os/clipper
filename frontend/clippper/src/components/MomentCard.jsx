import { useState } from 'react'
import FormatPicker from './FormatPicker'
import Toggle from './Toggle'
import { DEFAULT_CLIP_FORMAT } from '../services/api'
import { formatClock } from '../lib/format'

// The detector scores 0..1 (see backend/app/tasks/detect.py); people read /100.
function toPercent(score) {
  return Number.isFinite(Number(score)) ? Math.round(Number(score) * 100) : null
}

const chipLabels = [
  ['hook', 'Hook'],
  ['shareability', 'Shareable'],
  ['completeness', 'Complete'],
  ['visual', 'Visual'],
]

function MomentCard({ moment, index, onGenerate, isGenerating = false, isTop = false }) {
  const [format, setFormat] = useState(DEFAULT_CLIP_FORMAT)
  const [captions, setCaptions] = useState(true)

  const scores = moment?.scores || {}
  const finalScore = toPercent(scores.final)

  return (
    <article className="moment-card">
      <div className="moment-card-top">
        <div>
          <div className="moment-rank">
            <span className="moment-time">
              {formatClock(moment?.start_sec)} – {formatClock(moment?.end_sec)}
            </span>
            {moment?.type ? <span className="type-chip">{moment.type}</span> : null}
          </div>
          <h3>{moment?.title || `Moment ${index + 1}`}</h3>
          {moment?.reason ? <p className="moment-reason">{moment.reason}</p> : null}
        </div>

        {finalScore != null ? (
          <span className={isTop ? 'moment-score is-top' : 'moment-score'} title="Overall score">
            {finalScore}
          </span>
        ) : null}
      </div>

      <div className="score-chips">
        {chipLabels.map(([key, label]) => {
          const value = toPercent(scores[key])
          return value == null ? null : (
            <span className="score-chip" key={key}>
              {label} <strong>{value}</strong>
            </span>
          )
        })}
      </div>

      <div className="moment-options">
        <FormatPicker disabled={isGenerating} onChange={setFormat} value={format} />
        <Toggle checked={captions} disabled={isGenerating} label="Captions" onChange={setCaptions} />
        <button
          className="button button-primary"
          disabled={isGenerating}
          onClick={() => onGenerate({ moment, index, format, captions })}
          type="button"
        >
          {isGenerating ? 'Sending to render…' : 'Generate clip'}
        </button>
      </div>
    </article>
  )
}

export default MomentCard
