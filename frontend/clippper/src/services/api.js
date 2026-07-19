import { runMultipartUpload } from './multipartUpload'

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
    const raw = await response.text()
    if (!raw) {
      return null
    }
    return JSON.parse(raw)
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

async function requestJson(path, { method = 'GET', token, getToken, body } = {}) {
  // Long uploads outlive a single Clerk token (~60s), so callers can pass a
  // getToken provider to fetch a fresh token per request instead of a fixed one.
  const authToken = getToken ? await getToken() : token
  requireToken(authToken)

  const response = await fetch(getApiUrl(path), {
    method,
    headers: {
      Authorization: `Bearer ${authToken}`,
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

export async function initVideoUpload({ file, token, getToken }) {
  const data = await requestJson('/videos/init', {
    method: 'POST',
    token,
    getToken,
    body: {
      filename: file.name,
      size: file.size,
    },
  })

  const isValidSingle = data?.mode === 'single' && data?.upload_url
  const isValidMultipart = data?.mode === 'multipart' && data?.upload_id && data?.part_size && data?.part_count

  if (!data?.video_id || (!isValidSingle && !isValidMultipart)) {
    throw new ApiError('The upload could not be started because the server response was incomplete.', {
      details: data,
    })
  }

  return data
}

export async function getPartUploadUrls({ videoId, partNumbers, getToken }) {
  return requestJson(`/videos/${encodeURIComponent(videoId)}/parts`, {
    method: 'POST',
    getToken,
    body: { part_numbers: partNumbers },
  })
}

export async function getUploadStatus({ videoId, getToken }) {
  return requestJson(`/videos/${encodeURIComponent(videoId)}/upload-status`, {
    method: 'GET',
    getToken,
  })
}

export async function abortVideoUpload({ videoId, token, getToken }) {
  return requestJson(`/videos/${encodeURIComponent(videoId)}/abort`, {
    method: 'POST',
    token,
    getToken,
  })
}

export function uploadFileToSignedUrl({ file, uploadUrl, onProgress, signal }) {
  return new Promise((resolve, reject) => {
    if (!uploadUrl) {
      reject(new ApiError('The upload URL is missing.'))
      return
    }

    const xhr = new XMLHttpRequest()
    xhr.timeout = 360000
    signal?.addEventListener('abort', () => xhr.abort(), { once: true })

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

export async function completeVideoUpload({ videoId, parts, token, getToken }) {
  const data = await requestJson('/videos/complete', {
    method: 'POST',
    token,
    getToken,
    body: {
      video_id: videoId,
      parts: parts || undefined,
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

export async function getVideoMetadata({ videoId, token }) {
  return requestJson(`/videos/${encodeURIComponent(videoId)}/metadata`, {
    method: 'GET',
    token,
  })
}

export async function getVideoMoments({ videoId, token }) {
  return requestJson(`/videos/${encodeURIComponent(videoId)}/moments`, {
    method: 'GET',
    token,
  })
}

export async function deleteVideo({ videoId, token }) {
  const data = await requestJson(`/videos/${encodeURIComponent(videoId)}`, {
    method: 'DELETE',
    token,
  })

  if (!data?.video_id) {
    throw new ApiError('The video may have been deleted, but the server response was incomplete.', {
      details: data,
    })
  }

  return data
}

export const CLIP_FORMATS = ['9:16', '1:1', '16:9']
export const DEFAULT_CLIP_FORMAT = '9:16'

// Rendering is queued on a worker, so this returns as soon as the job is
// accepted. Poll getClip() for the finished URL.
export async function createClip({
  videoId,
  startSec,
  endSec,
  format = DEFAULT_CLIP_FORMAT,
  captions = false,
  momentId,
  token,
}) {
  const data = await requestJson('/clips/create', {
    method: 'POST',
    token,
    body: {
      video_id: videoId,
      start_sec: startSec,
      end_sec: endSec,
      format,
      captions,
      moment_id: momentId || undefined,
    },
  })

  if (!data?.clip_id) {
    throw new ApiError('The clip was queued, but the server did not return a clip id.', {
      details: data,
    })
  }

  return data
}

// Every clip already on record for a video, including the ones detect rendered
// without being asked. The grid reads this so those clips show up as ready
// instead of looking unrendered and being paid for twice.
export async function listClips({ videoId, token }) {
  return requestJson(`/clips?video_id=${encodeURIComponent(videoId)}`, {
    method: 'GET',
    token,
  })
}

export async function getClip({ clipId, token }) {
  return requestJson(`/clips/${encodeURIComponent(clipId)}`, {
    method: 'GET',
    token,
  })
}

export async function uploadVideoFile({
  file,
  token,
  getToken,
  onProgress,
  onStepChange,
  onInit,
  signal,
  resume,
}) {
  if (!file) {
    throw new ApiError('Choose a video file before uploading.')
  }

  if (!file.size) {
    throw new ApiError('The selected file is empty.')
  }

  const tokenProvider = getToken || (async () => token)

  onStepChange?.('initializing')

  let plan = null
  if (resume?.videoId) {
    const status = await getUploadStatus({ videoId: resume.videoId, getToken: tokenProvider })
    if (status?.resumable) {
      plan = { ...status, video_id: resume.videoId }
    }
    // Not resumable (expired/aborted upstream): fall through to a fresh init.
  }
  if (!plan) {
    plan = await initVideoUpload({ file, getToken: tokenProvider })
  }

  const videoId = plan.video_id
  onInit?.({ videoId, mode: plan.mode })

  onStepChange?.('uploading')
  let parts
  if (plan.mode === 'multipart') {
    parts = await runMultipartUpload({
      file,
      partSize: plan.part_size,
      partCount: plan.part_count,
      alreadyUploaded: plan.uploaded_parts || [],
      signParts: (partNumbers) => getPartUploadUrls({ videoId, partNumbers, getToken: tokenProvider }),
      onProgress,
      signal,
    })
  } else {
    await uploadFileToSignedUrl({ file, uploadUrl: plan.upload_url, onProgress, signal })
  }

  onStepChange?.('completing')
  return completeVideoUpload({ videoId, parts, getToken: tokenProvider })
}
