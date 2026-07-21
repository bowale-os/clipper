import { useEffect, useRef, useState } from 'react'
import { useVideoUpload } from '../hooks/useVideoUpload'
import LiveStatus from './LiveStatus'
import { UploadIcon } from './icons'
import { formatBytes } from '../lib/format'

const busyCopy = {
  initializing: 'Getting a secure upload ready.',
  uploading: 'Uploading. You can leave this tab open.',
  completing: 'Wrapping up.',
}

/**
 * The one job of the main screen. Picking a file stages it and waits: nothing
 * leaves the machine until you press Upload, so a wrong pick costs a click
 * rather than an hour of someone's bandwidth.
 */
function DropZone({ large = false, onUploaded, resumeTarget: initialResumeTarget = null }) {
  const fileInputRef = useRef(null)
  const [isDragging, setIsDragging] = useState(false)
  const {
    cancelUpload,
    error,
    file,
    isBusy,
    progress,
    resetUpload,
    resumeTarget,
    selectFile,
    status,
    uploadSelectedFile,
  } = useVideoUpload({ resumeTarget: initialResumeTarget })

  const isResuming = Boolean(resumeTarget)
  const isSelected = status === 'selected'
  const notifiedRef = useRef(false)

  useEffect(() => {
    if (status !== 'success' || notifiedRef.current) {
      return
    }

    notifiedRef.current = true
    onUploaded?.()

    // Hand the zone back so the next stream can go straight in.
    const timeoutId = window.setTimeout(() => {
      notifiedRef.current = false
      resetUpload()
    }, 2500)

    return () => window.clearTimeout(timeoutId)
    // resetUpload is recreated each render, so it is deliberately not a dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  function handleFileChange(event) {
    selectFile(event.target.files?.[0] || null)
    // Clear the native input so picking the same file again still fires `change`.
    event.target.value = ''
  }

  function handleDrop(event) {
    event.preventDefault()
    setIsDragging(false)

    if (!isBusy) {
      selectFile(event.dataTransfer.files?.[0] || null)
    }
  }

  function openPicker() {
    if (!isBusy) {
      fileInputRef.current?.click()
    }
  }

  const className = ['dropzone', large ? 'is-large' : '', isDragging ? 'is-dragging' : '']
    .filter(Boolean)
    .join(' ')

  return (
    <div>
      <input
        ref={fileInputRef}
        className="sr-only"
        type="file"
        accept="video/*,.mp4,.mov,.avi,.mkv"
        onChange={handleFileChange}
      />

      <div
        className={className}
        onClick={openPicker}
        onDragLeave={() => setIsDragging(false)}
        onDragOver={(event) => {
          event.preventDefault()
          setIsDragging(true)
        }}
        onDrop={handleDrop}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            openPicker()
          }
        }}
        role="button"
        tabIndex={isBusy ? -1 : 0}
        aria-disabled={isBusy}
      >
        <span className="dropzone-glyph">
          <UploadIcon size={20} />
        </span>

        <div className="dropzone-text">
          {isBusy ? (
            <>
              <strong>{file?.name || resumeTarget?.filename || 'Your video'}</strong>
              <span>{busyCopy[status] || 'Working on it.'}</span>
            </>
          ) : status === 'success' ? (
            <>
              <strong>Got it. We are watching this one now.</strong>
              <span>The clips turn up below when they are ready.</span>
            </>
          ) : isSelected ? (
            <>
              <strong>{file.name}</strong>
              <span>{formatBytes(file.size)}. Wrong one? Click here to pick another.</span>
            </>
          ) : isResuming ? (
            <>
              <strong>Pick "{resumeTarget.filename}" again to carry on</strong>
              <span>
                {formatBytes(resumeTarget.sizeBytes)}. We skip the parts you already sent.
              </span>
            </>
          ) : (
            <>
              <strong>Drop a video, or click to upload</strong>
              <span>MP4 or MOV. However long it is, we will get through it.</span>
            </>
          )}
        </div>

        {isBusy ? (
          <button
            className="button button-quiet button-small dropzone-cta"
            onClick={(event) => {
              event.stopPropagation()
              cancelUpload()
            }}
            type="button"
          >
            Cancel
          </button>
        ) : isSelected ? (
          <div className="dropzone-cta dropzone-confirm">
            <button
              className="button button-quiet button-small"
              onClick={(event) => {
                event.stopPropagation()
                resetUpload()
              }}
              type="button"
            >
              Clear
            </button>
            <button
              className="button button-primary"
              onClick={(event) => {
                event.stopPropagation()
                uploadSelectedFile()
              }}
              type="button"
            >
              {isResuming ? 'Resume upload' : 'Upload'}
            </button>
          </div>
        ) : (
          <span className="button button-primary dropzone-cta">Upload</span>
        )}
      </div>

      {isBusy ? (
        <div aria-live="polite" style={{ marginTop: 'var(--space-3)' }}>
          <div className="progress-meta">
            <LiveStatus status={status} />
            <strong>{progress}%</strong>
          </div>
          <div className="progress-track">
            <span style={{ width: `${progress}%` }} />
          </div>
        </div>
      ) : null}

      {error ? (
        <p className="message error" style={{ marginTop: 'var(--space-3)' }}>
          {error}
        </p>
      ) : null}
    </div>
  )
}

export default DropZone
