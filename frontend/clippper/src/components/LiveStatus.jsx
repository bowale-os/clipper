/* One status vocabulary for uploads, analysis, and renders. A live dot means
   something is actually moving; everything else sits still. */

const tones = {
  initializing: 'is-live',
  uploading: 'is-live',
  completing: 'is-live',
  uploaded: 'is-live',
  processing: 'is-live',
  waiting: 'is-live',
  queued: 'is-live',
  rendering: 'is-live',
  ready: 'is-good',
  success: 'is-good',
  error: 'is-bad',
}

const labels = {
  initializing: 'Getting ready',
  uploading: 'Uploading',
  completing: 'Wrapping up',
  uploaded: 'Finding moments',
  processing: 'Finding moments',
  waiting: 'Busy right now, still trying',
  queued: 'In the queue',
  rendering: 'Making the clip',
  ready: 'Ready',
  success: 'Done',
  error: 'Did not work',
}

function LiveStatus({ status, className = '' }) {
  const key = String(status || 'unknown')

  return (
    <span className={`live-status ${tones[key] || 'is-idle'} ${className}`.trim()}>
      {labels[key] || key}
    </span>
  )
}

export default LiveStatus
