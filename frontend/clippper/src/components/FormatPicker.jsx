import { CLIP_FORMATS } from '../services/api'

const platformHints = {
  '9:16': 'TikTok, Reels, Shorts',
  '1:1': 'Feed posts',
  '16:9': 'YouTube, Twitch',
}

function FormatPicker({ value, onChange, disabled = false }) {
  return (
    <div className="segmented" role="group" aria-label="Clip shape">
      {CLIP_FORMATS.map((format) => (
        <button
          aria-pressed={value === format}
          disabled={disabled}
          key={format}
          onClick={() => onChange(format)}
          title={platformHints[format]}
          type="button"
        >
          {format}
        </button>
      ))}
    </div>
  )
}

export default FormatPicker
