import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  abortVideoUpload,
  ApiError,
  AuthExpiredError,
  completeVideoUpload,
  createClip,
  deleteVideo,
  getClip,
  getPartUploadUrls,
  getUploadStatus,
  getUserVideos,
  getVideoMetadata,
  getVideoMoments,
  initVideoUpload,
  listClips,
  searchVideos,
  uploadVideoFile,
} from './api'

function jsonResponse(body, { status = 200, headers = {} } = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  })
}

let fetchMock

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function lastCall() {
  const [url, options] = fetchMock.mock.calls.at(-1)
  return { url, ...options, body: options.body ? JSON.parse(options.body) : undefined }
}

describe('request plumbing', () => {
  it('sends the bearer token, JSON headers and the right URL', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ready_videos: [] }))
    await getUserVideos({ token: 'tok' })
    const call = lastCall()
    expect(call.url).toBe('http://api.test/videos/')
    expect(call.method).toBe('GET')
    expect(call.headers).toEqual({ Authorization: 'Bearer tok', 'Content-Type': 'application/json' })
  })

  it('asks for a fresh token on every request when given a provider', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({})))
    const getToken = vi.fn().mockResolvedValueOnce('first').mockResolvedValueOnce('second')
    await getUploadStatus({ videoId: 'v', getToken })
    await getUploadStatus({ videoId: 'v', getToken })
    expect(fetchMock.mock.calls.map(([, o]) => o.headers.Authorization)).toEqual(['Bearer first', 'Bearer second'])
  })

  it('refuses to call the API without a token', async () => {
    await expect(getUserVideos({ token: null })).rejects.toBeInstanceOf(AuthExpiredError)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('treats a 401 as an expired session', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Token expired' }, { status: 401 }))
    const error = await getUserVideos({ token: 't' }).catch((e) => e)
    expect(error).toBeInstanceOf(AuthExpiredError)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(401)
    expect(error.message).toBe('Token expired')
  })

  it('turns error responses into ApiError with status, details and retry-after', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: 'Rate limit exceeded' }, { status: 429, headers: { 'retry-after': '42' } }),
    )
    const error = await getUserVideos({ token: 't' }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 429, message: 'Rate limit exceeded', retryAfterSec: 42 })
    expect(error.details).toEqual({ detail: 'Rate limit exceeded' })
  })

  it('reads FastAPI validation errors', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: [{ msg: 'Input should be greater than 0' }] }, { status: 422 }))
    const error = await getUserVideos({ token: 't' }).catch((e) => e)
    expect(error.message).toBe('Input should be greater than 0')
  })

  it('falls back to a generic message and handles plain-text bodies', async () => {
    fetchMock.mockResolvedValueOnce(new Response('', { status: 500, headers: { 'content-type': 'text/plain' } }))
    expect((await getUserVideos({ token: 't' }).catch((e) => e)).message).toBe('Request failed.')
    fetchMock.mockResolvedValueOnce(new Response('upstream down', { status: 502, headers: { 'content-type': 'text/plain' } }))
    expect((await getUserVideos({ token: 't' }).catch((e) => e)).message).toBe('upstream down')
  })

  it('copes with an empty JSON body', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 200, headers: { 'content-type': 'application/json' } }))
    expect(await getUserVideos({ token: 't' })).toBeNull()
  })
})

describe('endpoints', () => {
  beforeEach(() => fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ video_id: 'v1', clip_id: 'c1' }))))

  it('encodes ids and queries into the URL', async () => {
    await getVideoMetadata({ videoId: 'a/b c', token: 't' })
    expect(lastCall().url).toBe('http://api.test/videos/a%2Fb%20c/metadata')
    await getVideoMoments({ videoId: 'v', token: 't' })
    expect(lastCall().url).toBe('http://api.test/videos/v/moments')
    await searchVideos({ q: 'my talk & more', token: 't' })
    expect(lastCall().url).toBe('http://api.test/videos/search?q=my%20talk%20%26%20more')
    await listClips({ videoId: 'v 1', token: 't' })
    expect(lastCall().url).toBe('http://api.test/clips?video_id=v%201')
    await getClip({ clipId: 'c', token: 't' })
    expect(lastCall().url).toBe('http://api.test/clips/c')
  })

  it('uses the right verbs', async () => {
    await abortVideoUpload({ videoId: 'v', token: 't' })
    expect(lastCall()).toMatchObject({ method: 'POST', url: 'http://api.test/videos/v/abort' })
    await deleteVideo({ videoId: 'v', token: 't' })
    expect(lastCall()).toMatchObject({ method: 'DELETE', url: 'http://api.test/videos/v' })
    await getPartUploadUrls({ videoId: 'v', partNumbers: [1, 2], getToken: async () => 't' })
    expect(lastCall()).toMatchObject({ method: 'POST', body: { part_numbers: [1, 2] } })
  })

  it('createClip sends the snake_case body and defaults', async () => {
    await createClip({ videoId: 'v', startSec: 1, endSec: 9, token: 't' })
    expect(lastCall().body).toEqual({ video_id: 'v', start_sec: 1, end_sec: 9, format: '9:16', captions: false })
    await createClip({ videoId: 'v', startSec: 1, endSec: 9, format: '1:1', captions: true, momentId: 'm', token: 't' })
    expect(lastCall().body).toMatchObject({ format: '1:1', captions: true, moment_id: 'm' })
  })

  it('createClip rejects a response without a clip id', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}))
    await expect(createClip({ videoId: 'v', startSec: 1, endSec: 2, token: 't' })).rejects.toThrow(/clip id/)
  })

  it('deleteVideo rejects an unconfirmed deletion', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}))
    await expect(deleteVideo({ videoId: 'v', token: 't' })).rejects.toThrow(/incomplete/)
  })

  it('completeVideoUpload sends parts only when present, and wants a confirmation', async () => {
    await completeVideoUpload({ videoId: 'v', parts: [{ part_number: 1, etag: '"a"' }], token: 't' })
    expect(lastCall().body).toEqual({ video_id: 'v', parts: [{ part_number: 1, etag: '"a"' }] })
    await completeVideoUpload({ videoId: 'v', token: 't' })
    expect(lastCall().body).toEqual({ video_id: 'v' })
    fetchMock.mockResolvedValue(jsonResponse({}))
    await expect(completeVideoUpload({ videoId: 'v', token: 't' })).rejects.toThrow(/did not confirm/)
  })
})

describe('initVideoUpload', () => {
  const file = { name: 'talk.mp4', size: 1234 }

  it('posts the filename and size and accepts a single-upload plan', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ mode: 'single', video_id: 'v', upload_url: 'https://r2/put' }))
    const plan = await initVideoUpload({ file, token: 't' })
    expect(plan.mode).toBe('single')
    expect(lastCall().body).toEqual({ filename: 'talk.mp4', size: 1234 })
  })

  it('accepts a complete multipart plan', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ mode: 'multipart', video_id: 'v', upload_id: 'u', part_size: 5, part_count: 3 }),
    )
    expect((await initVideoUpload({ file, token: 't' })).part_count).toBe(3)
  })

  it.each([
    {},
    { video_id: 'v' },
    { mode: 'single', video_id: 'v' },
    { mode: 'multipart', video_id: 'v', upload_id: 'u' },
    { mode: 'single', upload_url: 'x' },
  ])('rejects an incomplete plan %j', async (body) => {
    fetchMock.mockResolvedValue(jsonResponse(body))
    await expect(initVideoUpload({ file, token: 't' })).rejects.toThrow(/incomplete/)
  })
})

describe('uploadVideoFile', () => {
  it('validates the file before touching the network', async () => {
    await expect(uploadVideoFile({ file: null, token: 't' })).rejects.toThrow(/Choose a video/)
    await expect(uploadVideoFile({ file: { name: 'a.mp4', size: 0 }, token: 't' })).rejects.toThrow(/empty/)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('resumes a multipart upload that is still resumable, skipping finished parts', async () => {
    const calls = []
    fetchMock.mockImplementation((url, options) => {
      calls.push(`${options.method} ${url.replace('http://api.test', '')}`)
      if (url.endsWith('/upload-status')) {
        return Promise.resolve(
          jsonResponse({
            resumable: true,
            mode: 'multipart',
            part_size: 4,
            part_count: 2,
            uploaded_parts: [
              { part_number: 1, etag: '"a"', size: 4 },
              { part_number: 2, etag: '"b"', size: 4 },
            ],
          }),
        )
      }
      return Promise.resolve(jsonResponse({ video_id: 'v-old' }))
    })
    const steps = []
    const onInit = vi.fn()
    const result = await uploadVideoFile({
      file: { name: 'a.mp4', size: 8, slice: vi.fn() },
      getToken: async () => 't',
      resume: { videoId: 'v-old' },
      onStepChange: (s) => steps.push(s),
      onInit,
    })
    expect(result.video_id).toBe('v-old')
    expect(calls).toEqual(['GET /videos/v-old/upload-status', 'POST /videos/complete'])
    expect(onInit).toHaveBeenCalledWith({ videoId: 'v-old', mode: 'multipart' })
    expect(steps).toEqual(['initializing', 'uploading', 'completing'])
    expect(JSON.parse(fetchMock.mock.calls.at(-1)[1].body).parts).toEqual([
      { part_number: 1, etag: '"a"' },
      { part_number: 2, etag: '"b"' },
    ])
  })

  it('starts fresh when the old upload can no longer be resumed', async () => {
    class OkXHR {
      upload = { addEventListener() {} }
      listeners = {}
      status = 200
      addEventListener(name, fn) {
        this.listeners[name] = fn
      }
      open() {}
      setRequestHeader() {}
      send() {
        queueMicrotask(() => this.listeners.load())
      }
    }
    vi.stubGlobal('XMLHttpRequest', OkXHR)
    const urls = []
    fetchMock.mockImplementation((url) => {
      urls.push(url.replace('http://api.test', ''))
      if (url.endsWith('/upload-status')) return Promise.resolve(jsonResponse({ resumable: false }))
      if (url.endsWith('/videos/init'))
        return Promise.resolve(jsonResponse({ mode: 'single', video_id: 'v-new', upload_url: 'https://r2/put' }))
      return Promise.resolve(jsonResponse({ video_id: 'v-new' }))
    })
    const result = await uploadVideoFile({
      file: { name: 'a.mp4', size: 8, slice: vi.fn() },
      token: 't',
      resume: { videoId: 'v-old' },
    })
    expect(urls).toEqual(['/videos/v-old/upload-status', '/videos/init', '/videos/complete'])
    expect(result.video_id).toBe('v-new')
  })
})
