import { useRef, useState } from 'react'
import { useVideoUpload } from '../hooks/useVideoUpload'
import StatusPill from './StatusPill'
import { UploadIcon } from './icons'
import { formatBytes } from '../lib/format'

const contentTypeOptions = [
  { label: 'General', value: 'default' },
  { label: 'Stream', value: 'stream' },
  { label: 'Podcast', value: 'podcast' },
  { label: 'Football', value: 'football' },
]

const statusCopy = {
  initializing: 'Getting a secure upload ready…',
  uploading: 'Uploading — you can leave this tab open.',
  completing: 'Wrapping up…',
}

function VideoUploadCard({ resumeTarget: initialResumeTarget = null }) {
  const fileInputRef = useRef(null)
  const [isDragging, setIsDragging] = useState(false)
  const {
    error,
    file,
    isBusy,
    progress,
    cancelUpload,
    resetUpload,
    result,
    resumeTarget,
    selectFile,
    setContentType,
    status,
    uploadSelectedFile,
    contentType,
  } = useVideoUpload({ resumeTarget: initialResumeTarget })

  const showProgress = ['uploading', 'completing', 'success'].includes(status)
  const canUpload = Boolean(file) && !isBusy && status !== 'success'
  const isResuming = Boolean(resumeTarget)

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

  function handleSubmit(event) {
    event.preventDefault()
    uploadSelectedFile()
  }

  return (
    <form className="card upload-card" onSubmit={handleSubmit}>
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Upload</p>
          <h2>{isResuming ? 'Resume your upload' : 'Drop in a stream'}</h2>
        </div>
        {isBusy || status === 'success' ? <StatusPill status={status} /> : null}
      </div>

      <input
        ref={fileInputRef}
        className="sr-only"
        type="file"
        accept="video/*,.mp4,.mov,.avi,.mkv"
        onChange={handleFileChange}
      />

      <button
        className={isDragging ? 'dropzone is-dragging' : 'dropzone'}
        disabled={isBusy}
        onClick={() => fileInputRef.current?.click()}
        onDragLeave={() => setIsDragging(false)}
        onDragOver={(event) => {
          event.preventDefault()
          setIsDragging(true)
        }}
        onDrop={handleDrop}
        type="button"
      >
        <span className="dropzone-glyph">
          <UploadIcon size={20} />
        </span>
        <strong>
          {file ? file.name : isResuming ? `Re-select "${resumeTarget.filename}"` : 'Drop a video or click to browse'}
        </strong>
        <span>
          {file
            ? formatBytes(file.size)
            : isResuming
              ? `${formatBytes(resumeTarget.sizeBytes)} — we'll skip the chunks you already sent`
              : 'MP4, MOV, AVI, or MKV — long streams welcome'}
        </span>
      </button>

      <div className="upload-options">
        <div className="field">
          <span>What kind of video is this?</span>
          <div className="segmented" role="group" aria-label="Detection type">
            {contentTypeOptions.map((option) => (
              <button
                aria-pressed={contentType === option.value}
                disabled={isBusy}
                key={option.value}
                onClick={() => setContentType(option.value)}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {showProgress ? (
        <div aria-live="polite">
          <div className="progress-meta">
            <span>{statusCopy[status] || 'Uploaded — analysis is running.'}</span>
            <strong>{progress}%</strong>
          </div>
          <div className="progress-track">
            <span style={{ width: `${progress}%` }} />
          </div>
        </div>
      ) : null}

      {error ? <p className="message error">{error}</p> : null}

      {status === 'success' ? (
        <div className="message success">
          <strong>Upload complete — we'll handle the boring stuff.</strong>
          <span>We're scanning this video for clip-worthy moments. It'll turn up in your library.</span>
          <span className="mono">{result?.video_id}</span>
        </div>
      ) : null}

      <div className="upload-actions">
        <button className="button button-primary button-large" type="submit" disabled={!canUpload}>
          {isBusy ? 'Uploading…' : isResuming ? 'Resume upload' : 'Upload and find moments'}
        </button>
        {isBusy ? (
          <button className="button button-danger" type="button" onClick={cancelUpload}>
            Cancel
          </button>
        ) : (
          <button
            className="button button-secondary"
            type="button"
            onClick={resetUpload}
            disabled={!file && !error && !isResuming}
          >
            Clear
          </button>
        )}
      </div>
    </form>
  )
}

export default VideoUploadCard
