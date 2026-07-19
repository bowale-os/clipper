/* Shared formatters. They live here so every screen reads the same way. */

export function formatBytes(bytes) {
  if (!bytes) {
    return 'Unknown size'
  }

  const units = ['B', 'KB', 'MB', 'GB']
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** exponent

  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`
}

export function formatClock(totalSeconds, { includeHours = false } = {}) {
  const numeric = Number(totalSeconds)
  const safeSeconds = Number.isFinite(numeric) ? Math.max(0, Math.floor(numeric)) : 0
  const hours = Math.floor(safeSeconds / 3600)
  const minutes = Math.floor((safeSeconds % 3600) / 60)
  const seconds = safeSeconds % 60

  if (includeHours || hours > 0) {
    return [hours, minutes, seconds].map((part) => String(part).padStart(2, '0')).join(':')
  }

  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

/**
 * Reads the timecodes people actually type: "90", "1:30", or "01:02:30".
 * Returns NaN for anything it can't make sense of, so callers can validate.
 */
export function parseTimecode(value) {
  const raw = String(value ?? '').trim()

  if (!raw) {
    return Number.NaN
  }

  const parts = raw.split(':')

  if (parts.length > 3 || parts.some((part) => part === '' || !/^\d*\.?\d*$/.test(part))) {
    return Number.NaN
  }

  return parts.reduce((total, part) => total * 60 + Number(part), 0)
}

export function formatDate(value) {
  if (!value) {
    return 'No date'
  }

  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return String(value)
  }

  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

// The detector scores 0..1 (see backend/app/tasks/detect.py); people read /100.
export function toScore(value) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? Math.round(numeric * 100) : null
}

export function getVideoId(video) {
  return video?._id || video?.id || video?.video_id || ''
}

export function getFileExtension(filename) {
  const extension = String(filename || '').split('.').pop()
  return extension && extension.length <= 4 ? extension : 'video'
}
