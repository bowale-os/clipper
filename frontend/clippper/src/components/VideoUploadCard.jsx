import { useRef } from 'react'
import { useVideoUpload } from '../hooks/useVideoUpload'

const contentTypeOptions = [
  { label: 'Default', value: 'default' },
  { label: 'Football', value: 'football' },
  { label: 'Stream', value: 'stream' },
  { label: 'Podcast', value: 'podcast' },
]

function formatBytes(bytes) {
  if (!bytes) {
    return '0 MB'
  }

  const units = ['B', 'KB', 'MB', 'GB']
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** exponent

  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`
}

function getStatusText(status) {
  const statusText = {
    idle: 'Choose a long-form video to begin.',
    selected: 'Ready to upload.',
    initializing: 'Preparing a secure upload...',
    uploading: 'Uploading your video...',
    completing: 'Finishing upload...',
    success: 'Upload complete!',
    error: 'Upload needs attention.',
  }

  return statusText[status] || statusText.idle
}

function VideoUploadCard({ resumeTarget: initialResumeTarget = null }) {
  const fileInputRef = useRef(null)
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
    setAutoDetect,
    setContentType,
    status,
    uploadSelectedFile,
    autoDetect,
    contentType,
  } = useVideoUpload({ resumeTarget: initialResumeTarget })

  const showProgress = ['uploading', 'completing', 'success'].includes(status)
  const canUpload = Boolean(file) && !isBusy && status !== 'success'
  const isResuming = Boolean(resumeTarget)

  function openFilePicker() {
    fileInputRef.current?.click()
  }

  function handleFileChange(event) {
    selectFile(event.target.files?.[0] || null)
    // Clear the native input so picking the same file again still fires `change`.
    event.target.value = ''
  }

  function handleSubmit(event) {
    event.preventDefault()
    uploadSelectedFile()
  }

  return (
    <form className="dashboard-panel upload-card" onSubmit={handleSubmit}>
      <div className="upload-card-header">
        <div>
          <p className="panel-label">Video upload</p>
          <h2>{isResuming ? 'Resume your upload' : 'Upload a long-form video'}</h2>
        </div>
        <span className={`upload-status ${status}`}>{getStatusText(status)}</span>
      </div>

      <input
        ref={fileInputRef}
        className="sr-only"
        type="file"
        accept="video/*,.mp4,.mov,.avi,.mkv"
        onChange={handleFileChange}
      />

      <button className="upload-picker" type="button" onClick={openFilePicker} disabled={isBusy}>
        <span className="upload-icon">+</span>
        <span>
          {file
            ? file.name
            : isResuming
              ? `Re-select "${resumeTarget.filename}" to resume`
              : 'Choose a video file'}
          <small>
            {file
              ? formatBytes(file.size)
              : isResuming
                ? `${formatBytes(resumeTarget.sizeBytes)} — already-uploaded chunks will be skipped`
                : 'MP4, MOV, AVI, or MKV'}
          </small>
        </span>
      </button>

      <label className="upload-auto-detect">
        <input
          type="checkbox"
          checked={autoDetect}
          onChange={(event) => setAutoDetect(event.target.checked)}
          disabled={isBusy}
        />
        <span>
          <strong>Auto detect moments</strong>
          <small>Start backend analysis as soon as the upload completes.</small>
        </span>
      </label>

      {autoDetect ? (
        <label className="upload-content-type">
          <span>Detection type</span>
          <select value={contentType} onChange={(event) => setContentType(event.target.value)} disabled={isBusy}>
            {contentTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {showProgress ? (
        <div className="upload-progress" aria-label="Upload progress">
          <div className="upload-progress-meta">
            <span>{getStatusText(status)}</span>
            <strong>{progress}%</strong>
          </div>
          <div className="upload-progress-track">
            <span style={{ width: `${progress}%` }} />
          </div>
        </div>
      ) : null}

      {error ? <p className="upload-message error">{error}</p> : null}

      {status === 'success' ? (
        <div className="upload-message success">
          <strong>Upload complete!</strong>
          {autoDetect ? <span>Auto detection has been requested for this video.</span> : null}
          <span>Video ID: {result?.video_id}</span>
        </div>
      ) : null}

      <div className="upload-actions">
        <button className="button button-primary dashboard-action" type="submit" disabled={!canUpload}>
          {isBusy ? 'Uploading...' : isResuming ? 'Resume upload' : 'Upload'}
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
