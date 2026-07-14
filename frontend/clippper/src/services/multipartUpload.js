export class PartUploadError extends Error {
  constructor(message, { status } = {}) {
    super(message)
    this.name = 'PartUploadError'
    this.status = status
  }
}

const ETAG_CORS_HINT =
  'The upload finished but the storage response was unreadable. ' +
  'The R2 bucket CORS policy must expose the ETag header.'

function throwIfAborted(signal) {
  if (signal?.aborted) {
    throw new PartUploadError('The upload was cancelled.')
  }
}

function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)

    function onAbort() {
      clearTimeout(timeoutId)
      reject(new PartUploadError('The upload was cancelled.'))
    }

    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

export function uploadPartXhr({ blob, url, onPartProgress, signal }) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()

    function onAbort() {
      xhr.abort()
    }
    signal?.addEventListener('abort', onAbort, { once: true })

    function cleanup() {
      signal?.removeEventListener('abort', onAbort)
    }

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        onPartProgress?.(event.loaded)
      }
    })

    xhr.addEventListener('load', () => {
      cleanup()

      if (xhr.status >= 200 && xhr.status < 300) {
        const etag = xhr.getResponseHeader('ETag')
        if (!etag) {
          reject(new PartUploadError(ETAG_CORS_HINT))
          return
        }
        onPartProgress?.(blob.size)
        resolve(etag)
        return
      }

      reject(new PartUploadError('A chunk of the upload failed.', { status: xhr.status }))
    })

    xhr.addEventListener('error', () => {
      cleanup()
      reject(new PartUploadError('A chunk of the upload failed because of a network error.'))
    })

    xhr.addEventListener('abort', () => {
      cleanup()
      reject(new PartUploadError('The upload was cancelled.'))
    })

    xhr.open('PUT', url)
    xhr.send(blob)
  })
}

/**
 * Uploads a file to R2 in parallel chunks and returns the full parts list for /videos/complete.
 *
 * signParts(partNumbers) must resolve to { urls: { "<partNumber>": presignedUrl } }.
 * alreadyUploaded parts (from /upload-status on resume) are skipped; their etags are
 * carried into the result and their bytes seed the progress bar.
 */
export async function runMultipartUpload({
  file,
  partSize,
  partCount,
  signParts,
  alreadyUploaded = [],
  onProgress,
  signal,
  concurrency = 4,
  maxRetries = 3,
  batchSize = 100,
}) {
  const controller = new AbortController()
  function abortFromOuter() {
    controller.abort()
  }
  signal?.addEventListener('abort', abortFromOuter, { once: true })

  const doneParts = new Map(alreadyUploaded.map((p) => [p.part_number, p.etag]))
  const loadedBytes = new Map(alreadyUploaded.map((p) => [p.part_number, p.size ?? partSize]))

  const pending = []
  for (let n = 1; n <= partCount; n += 1) {
    if (!doneParts.has(n)) {
      pending.push(n)
    }
  }

  function reportProgress() {
    if (!onProgress) {
      return
    }
    let uploaded = 0
    for (const bytes of loadedBytes.values()) {
      uploaded += bytes
    }
    // Hold at 99 until /videos/complete confirms the object.
    onProgress(Math.min(99, Math.round((uploaded / file.size) * 100)))
  }
  reportProgress()

  // Presigned URLs are fetched lazily in batches as the workers drain them.
  const urls = new Map()
  let nextBatchStart = 0
  let batchPromise = null

  async function fetchNextBatch() {
    const batch = pending.slice(nextBatchStart, nextBatchStart + batchSize)
    if (!batch.length) {
      return
    }
    nextBatchStart += batch.length
    const { urls: signed } = await signParts(batch)
    for (const [partNumber, url] of Object.entries(signed || {})) {
      urls.set(Number(partNumber), url)
    }
  }

  async function ensureUrl(partNumber) {
    while (!urls.has(partNumber)) {
      throwIfAborted(controller.signal)
      if (!batchPromise) {
        batchPromise = fetchNextBatch().finally(() => {
          batchPromise = null
        })
      }
      await batchPromise
    }
    return urls.get(partNumber)
  }

  async function uploadPart(partNumber) {
    const start = (partNumber - 1) * partSize
    const blob = file.slice(start, Math.min(start + partSize, file.size))

    for (let attempt = 0; ; attempt += 1) {
      throwIfAborted(controller.signal)

      try {
        const url = await ensureUrl(partNumber)
        const etag = await uploadPartXhr({
          blob,
          url,
          signal: controller.signal,
          onPartProgress: (loaded) => {
            loadedBytes.set(partNumber, loaded)
            reportProgress()
          },
        })
        doneParts.set(partNumber, etag)
        loadedBytes.set(partNumber, blob.size)
        reportProgress()
        return
      } catch (error) {
        loadedBytes.set(partNumber, 0)
        reportProgress()

        if (controller.signal.aborted || attempt >= maxRetries) {
          throw error
        }

        if (error?.status === 403) {
          // Presigned URL expired; re-sign just this part.
          const { urls: fresh } = await signParts([partNumber])
          const freshUrl = fresh?.[String(partNumber)]
          if (freshUrl) {
            urls.set(partNumber, freshUrl)
          }
        }

        await delay(1000 * 2 ** attempt, controller.signal)
      }
    }
  }

  let cursor = 0
  async function worker() {
    while (cursor < pending.length) {
      throwIfAborted(controller.signal)
      const partNumber = pending[cursor]
      cursor += 1
      await uploadPart(partNumber)
    }
  }

  try {
    const workerCount = Math.min(concurrency, pending.length)
    await Promise.all(Array.from({ length: workerCount }, () => worker()))
  } catch (error) {
    // Stop the other in-flight parts before surfacing the failure.
    controller.abort()
    throw error
  } finally {
    signal?.removeEventListener('abort', abortFromOuter)
  }

  return Array.from(doneParts, ([partNumber, etag]) => ({ part_number: partNumber, etag }))
}
