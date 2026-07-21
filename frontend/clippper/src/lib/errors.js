import { ApiError } from '../services/api'

function formatWait(seconds) {
  if (!seconds || seconds < 1) {
    return 'a moment'
  }

  if (seconds < 60) {
    const whole = Math.ceil(seconds)
    return `${whole} second${whole === 1 ? '' : 's'}`
  }

  const minutes = Math.round(seconds / 60)
  return `${minutes} minute${minutes === 1 ? '' : 's'}`
}

export function getReadableError(error, fallback = 'Something went wrong.') {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return `Pause. Slow down on that. Try again in ${formatWait(error.retryAfterSec)}.`
    }

    if (error.status && error.status >= 500) {
      return 'Something went wrong on our end. Please try again in a moment.'
    }

    return error.message || fallback
  }

  if (error instanceof Error) {
    return error.message
  }

  return fallback
}
