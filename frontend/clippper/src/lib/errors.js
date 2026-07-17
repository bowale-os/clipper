import { ApiError } from '../services/api'

export function getReadableError(error, fallback = 'Something went wrong.') {
  if (error instanceof ApiError) {
    return error.status ? `${error.message} (${error.status})` : error.message
  }

  if (error instanceof Error) {
    return error.message
  }

  return fallback
}
