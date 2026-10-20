import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PartUploadError, runMultipartUpload, uploadPartXhr } from './multipartUpload'

/* A scriptable XMLHttpRequest. `behaviour(url, attempt)` decides what each PUT does:
   { status, etag } to finish, 'network' to fail, or 'hang' to wait until aborted. */
let behaviour
let attempts
let inFlight
let maxInFlight

class FakeXHR {
  constructor() {
    this.listeners = {}
    this.upload = { addEventListener: (name, fn) => (this.uploadListeners[name] = fn) }
    this.uploadListeners = {}
    this.status = 0
  }

  addEventListener(name, fn) {
    this.listeners[name] = fn
  }

  open(method, url) {
    this.method = method
    this.url = url
  }

  getResponseHeader(name) {
    return name === 'ETag' ? this.etag ?? null : null
  }

  abort() {
    this.finished = true
    inFlight -= 1
    this.listeners.abort?.()
  }

  send(blob) {
    attempts[this.url] = (attempts[this.url] ?? 0) + 1
    inFlight += 1
    maxInFlight = Math.max(maxInFlight, inFlight)
    const outcome = behaviour(this.url, attempts[this.url])
    if (outcome === 'hang') return
    queueMicrotask(() => {
      if (this.finished) return
      inFlight -= 1
      this.finished = true
      if (outcome === 'network') {
        this.listeners.error?.()
        return
      }
      this.uploadListeners.progress?.({ lengthComputable: true, loaded: blob.size })
      this.status = outcome.status
      this.etag = outcome.etag
      this.listeners.load?.()
    })
  }
}

class FakeFile {
  constructor(size) {
    this.size = size
  }

  slice(start, end) {
    return { size: end - start, start }
  }
}

const ok = (n) => ({ status: 200, etag: `"etag-${n}"` })

function signer(record = []) {
  return vi.fn(async (partNumbers) => {
    record.push(partNumbers)
    return { urls: Object.fromEntries(partNumbers.map((n) => [String(n), `https://r2/part/${n}`])) }
  })
}

beforeEach(() => {
  attempts = {}
  inFlight = 0
  maxInFlight = 0
  behaviour = (url) => ok(url.split('/').pop())
  vi.stubGlobal('XMLHttpRequest', FakeXHR)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('uploadPartXhr', () => {
  it('resolves with the etag and reports the part size', async () => {
    const onPartProgress = vi.fn()
    const etag = await uploadPartXhr({ blob: { size: 10 }, url: 'https://r2/part/1', onPartProgress })
    expect(etag).toBe('"etag-1"')
    expect(onPartProgress).toHaveBeenLastCalledWith(10)
  })

  it('explains the CORS setup when the etag header is unreadable', async () => {
    behaviour = () => ({ status: 200, etag: null })
    await expect(uploadPartXhr({ blob: { size: 1 }, url: 'u' })).rejects.toThrow(/CORS/)
  })

  it('carries the HTTP status on failures', async () => {
    behaviour = () => ({ status: 403 })
    const error = await uploadPartXhr({ blob: { size: 1 }, url: 'u' }).catch((e) => e)
    expect(error).toBeInstanceOf(PartUploadError)
    expect(error.status).toBe(403)
  })

  it('reports network errors and cancellation', async () => {
    behaviour = () => 'network'
    await expect(uploadPartXhr({ blob: { size: 1 }, url: 'u' })).rejects.toThrow(/network error/)

    behaviour = () => 'hang'
    const controller = new AbortController()
    const pending = uploadPartXhr({ blob: { size: 1 }, url: 'u', signal: controller.signal })
    controller.abort()
    await expect(pending).rejects.toThrow(/cancelled/)
  })
})

describe('runMultipartUpload', () => {
  it('uploads every part and returns the parts list in order', async () => {
    const file = new FakeFile(10)
    const parts = await runMultipartUpload({ file, partSize: 4, partCount: 3, signParts: signer() })
    expect(parts).toEqual([
      { part_number: 1, etag: '"etag-1"' },
      { part_number: 2, etag: '"etag-2"' },
      { part_number: 3, etag: '"etag-3"' },
    ])
  })

  it('slices the file into part-sized blobs with a short final part', async () => {
    const file = new FakeFile(10)
    const slice = vi.spyOn(file, 'slice')
    await runMultipartUpload({ file, partSize: 4, partCount: 3, signParts: signer() })
    expect(slice.mock.calls.map(([a, b]) => [a, b]).sort()).toEqual([[0, 4], [4, 8], [8, 10]])
  })

  it('never runs more than `concurrency` uploads at once', async () => {
    behaviour = (url) => ok(url.split('/').pop())
    await runMultipartUpload({ file: new FakeFile(80), partSize: 10, partCount: 8, signParts: signer(), concurrency: 3 })
    expect(maxInFlight).toBeLessThanOrEqual(3)
    expect(maxInFlight).toBeGreaterThan(1)
  })

  it('signs URLs lazily in batches', async () => {
    const record = []
    await runMultipartUpload({ file: new FakeFile(50), partSize: 10, partCount: 5, signParts: signer(record), batchSize: 2 })
    expect(record).toEqual([[1, 2], [3, 4], [5]])
  })

  it('skips parts that were already uploaded and keeps their etags', async () => {
    const record = []
    const parts = await runMultipartUpload({
      file: new FakeFile(12),
      partSize: 4,
      partCount: 3,
      signParts: signer(record),
      alreadyUploaded: [{ part_number: 1, etag: '"old-1"', size: 4 }, { part_number: 3, etag: '"old-3"', size: 4 }],
    })
    expect(record).toEqual([[2]])
    expect(Object.keys(attempts)).toEqual(['https://r2/part/2'])
    expect(parts).toEqual([
      { part_number: 1, etag: '"old-1"' },
      { part_number: 3, etag: '"old-3"' },
      { part_number: 2, etag: '"etag-2"' },
    ])
  })

  it('seeds progress from resumed parts and holds at 99 until the server confirms', async () => {
    const seen = []
    await runMultipartUpload({
      file: new FakeFile(8),
      partSize: 4,
      partCount: 2,
      signParts: signer(),
      alreadyUploaded: [{ part_number: 1, etag: '"a"', size: 4 }],
      onProgress: (pct) => seen.push(pct),
    })
    expect(seen[0]).toBe(50)
    expect(Math.max(...seen)).toBe(99)
    expect(seen).toEqual([...seen].sort((a, b) => a - b))
  })

  it('does nothing when every part is already there', async () => {
    const sign = signer()
    const parts = await runMultipartUpload({
      file: new FakeFile(4),
      partSize: 4,
      partCount: 1,
      signParts: sign,
      alreadyUploaded: [{ part_number: 1, etag: '"a"' }],
    })
    expect(sign).not.toHaveBeenCalled()
    expect(parts).toEqual([{ part_number: 1, etag: '"a"' }])
  })

  it('retries a failed part with backoff and then succeeds', async () => {
    vi.useFakeTimers()
    behaviour = (url, attempt) => (url.endsWith('/2') && attempt < 3 ? 'network' : ok(url.split('/').pop()))
    const run = runMultipartUpload({ file: new FakeFile(8), partSize: 4, partCount: 2, signParts: signer(), concurrency: 1 })
    await vi.advanceTimersByTimeAsync(1000 + 2000)
    const parts = await run
    expect(attempts['https://r2/part/2']).toBe(3)
    expect(parts.map((p) => p.part_number)).toEqual([1, 2])
  })

  it('re-signs just that part when its URL has expired (403)', async () => {
    vi.useFakeTimers()
    const record = []
    const sign = vi.fn(async (nums) => {
      record.push(nums)
      const version = record.length
      return { urls: Object.fromEntries(nums.map((n) => [String(n), `https://r2/v${version}/part/${n}`])) }
    })
    behaviour = (url) => (url.includes('/v1/') ? { status: 403 } : ok(url.split('/').pop()))
    const run = runMultipartUpload({ file: new FakeFile(4), partSize: 4, partCount: 1, signParts: sign })
    await vi.advanceTimersByTimeAsync(1000)
    const parts = await run
    expect(record).toEqual([[1], [1]])
    expect(parts).toEqual([{ part_number: 1, etag: '"etag-1"' }])
  })

  it('gives up after maxRetries and surfaces the error', async () => {
    vi.useFakeTimers()
    behaviour = () => ({ status: 500 })
    const run = runMultipartUpload({
      file: new FakeFile(4), partSize: 4, partCount: 1, signParts: signer(), maxRetries: 2,
    }).catch((e) => e)
    await vi.advanceTimersByTimeAsync(1000 + 2000)
    const error = await run
    expect(error).toBeInstanceOf(PartUploadError)
    expect(attempts['https://r2/part/1']).toBe(3)
  })

  it('stops the other parts when one fails for good', async () => {
    behaviour = (url) => (url.endsWith('/1') ? { status: 500 } : 'hang')
    const error = await runMultipartUpload({
      file: new FakeFile(8), partSize: 4, partCount: 2, signParts: signer(), maxRetries: 0, concurrency: 2,
    }).catch((e) => e)
    expect(error.status).toBe(500)
    expect(inFlight).toBe(0)
  })

  it('cancels when the caller aborts', async () => {
    behaviour = () => 'hang'
    const controller = new AbortController()
    const run = runMultipartUpload({
      file: new FakeFile(8), partSize: 4, partCount: 2, signParts: signer(), signal: controller.signal,
    }).catch((e) => e)
    await Promise.resolve()
    await new Promise((r) => setTimeout(r, 0))
    controller.abort()
    const error = await run
    expect(error).toBeInstanceOf(PartUploadError)
    expect(error.message).toMatch(/cancelled/)
    expect(inFlight).toBe(0)
  })
})
