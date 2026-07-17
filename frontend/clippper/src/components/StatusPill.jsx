/* One status vocabulary for videos and clips. Tone follows docs/DESIGN.md:
   cyan = in motion, lime = done, red = needs attention, grey = idle. */

const tones = {
  uploading: 'is-motion',
  initializing: 'is-motion',
  completing: 'is-motion',
  processing: 'is-motion',
  queued: 'is-motion',
  rendering: 'is-motion',
  uploaded: 'is-good',
  ready: 'is-good',
  success: 'is-good',
  error: 'is-bad',
}

const labels = {
  uploaded: 'analyzing',
  processing: 'analyzing',
  queued: 'in queue',
  rendering: 'rendering',
  ready: 'ready',
  error: 'failed',
  uploading: 'uploading',
}

function StatusPill({ status, className = '' }) {
  const key = String(status || 'unknown')

  return (
    <span className={`status-pill ${tones[key] || 'is-idle'} ${className}`.trim()}>
      {labels[key] || key}
    </span>
  )
}

export default StatusPill
