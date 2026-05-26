const API_URL = import.meta.env.VITE_API_URL

export class ApiError extends Error {
  constructor(message, { status, details } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

export class AuthExpiredError extends ApiError {
  constructor(message = 'Your session expired. Please sign in again.') {
    super(message, { status: 401 })
    this.name = 'AuthExpiredError'
  }
}

function getApiUrl(path) {
  if (!API_URL) {
    throw new ApiError('VITE_API_URL is not configured.')
  }

  return `${API_URL}${path}`
}

async function parseResponse(response) {
  const contentType = response.headers.get('content-type') || ''

  if (contentType.includes('application/json')) {
    return response.json()
  }

  return response.text()
}

function getResponseMessage(data, fallback) {
  if (data && typeof data === 'object' && 'detail' in data) {
    return Array.isArray(data.detail) ? data.detail[0]?.msg || fallback : data.detail
  }

  if (typeof data === 'string' && data.trim()) {
    return data
  }

  return fallback
}

async function requestJson(path, { method = 'GET', token, body } = {}) {
  requireToken(token)

  const response = await fetch(getApiUrl(path), {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  })

  const data = await parseResponse(response)

  if (response.status === 401) {
    throw new AuthExpiredError(getResponseMessage(data, 'Your session expired. Please sign in again.'))
  }

  if (!response.ok) {
    throw new ApiError(getResponseMessage(data, 'Request failed.'), {
      status: response.status,
      details: data,
    })
  }

  return data
}

function requireToken(token) {
  if (!token) {
    throw new AuthExpiredError()
  }
}

function getVideoContentType(file) {
  if (file.type) {
    return file.type
  }

  const extension = file.name.split('.').pop()?.toLowerCase()
  const contentTypes = {
    mp4: 'video/mp4',
    mov: 'video/quicktime',
    avi: 'video/x-msvideo',
    mkv: 'video/x-matroska',
  }

  return contentTypes[extension] || 'video/mp4'
}

export async function initVideoUpload({ file, token }) {
  const data = await requestJson('/videos/init', {
    method: 'POST',
    token,
    body: {
      filename: file.name,
      size: file.size,
    },
  })

  if (!data?.video_id || !data?.upload_url) {
    throw new ApiError('The upload could not be started because the server response was incomplete.', {
      details: data,
    })
  }

  return data
}

export function uploadFileToSignedUrl({ file, uploadUrl, onProgress }) {
  return new Promise((resolve, reject) => {
    if (!uploadUrl) {
      reject(new ApiError('The upload URL is missing.'))
      return
    }

    const xhr = new XMLHttpRequest()
    xhr.timeout = 120000

    xhr.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable || !onProgress) {
        return
      }

      onProgress(Math.round((event.loaded / event.total) * 100))
    })

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(100)
        resolve()
        return
      }

      reject(
        new ApiError('The file upload failed.', {
          status: xhr.status,
          details: xhr.responseText,
        }),
      )
    })

    xhr.addEventListener('error', () => {
      reject(new ApiError('The file upload failed because of a network error.'))
    })

    xhr.addEventListener('timeout', () => {
      reject(new ApiError('The file upload timed out. Please try again.'))
    })

    xhr.addEventListener('abort', () => {
      reject(new ApiError('The file upload was cancelled.'))
    })

    xhr.open('PUT', uploadUrl)
    xhr.setRequestHeader('Content-Type', getVideoContentType(file))
    xhr.send(file)
  })
}

export async function completeVideoUpload({ videoId, token }) {
  const data = await requestJson('/videos/complete', {
    method: 'POST',
    token,
    body: {
      video_id: videoId,
    },
  })

  if (!data?.video_id) {
    throw new ApiError('The upload finished, but the server did not confirm the video.', {
      details: data,
    })
  }

  return data
}

export async function getUserVideos({ token }) {
  return requestJson('/videos/', {
    method: 'GET',
    token,
  })
}

export async function uploadVideoFile({ file, token, onProgress, onStepChange }) {
  if (!file) {
    throw new ApiError('Choose a video file before uploading.')
  }

  if (!file.size) {
    throw new ApiError('The selected file is empty.')
  }

  onStepChange?.('initializing')
  const { video_id: videoId, upload_url: uploadUrl } = await initVideoUpload({ file, token })

  onStepChange?.('uploading')
  await uploadFileToSignedUrl({ file, uploadUrl, onProgress })

  onStepChange?.('completing')
  return completeVideoUpload({ videoId, token })
}
