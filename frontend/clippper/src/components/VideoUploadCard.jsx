import { useRef } from 'react'
import { useVideoUpload } from '../hooks/useVideoUpload'

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

function VideoUploadCard() {
  const fileInputRef = useRef(null)
  const {
    error,
    file,
    isBusy,
    progress,
    resetUpload,
    result,
    selectFile,
    status,
    uploadSelectedFile,
  } = useVideoUpload()

  const showProgress = ['uploading', 'completing', 'success'].includes(status)
  const canUpload = Boolean(file) && !isBusy && status !== 'success'

  function openFilePicker() {
    fileInputRef.current?.click()
  }

  function handleFileChange(event) {
    selectFile(event.target.files?.[0] || null)
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
          <h2>Upload a long-form video</h2>
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
          {file ? file.name : 'Choose a video file'}
          <small>{file ? formatBytes(file.size) : 'MP4, MOV, AVI, or MKV'}</small>
        </span>
      </button>

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
          <span>Video ID: {result?.video_id}</span>
        </div>
      ) : null}

      <div className="upload-actions">
        <button className="button button-primary dashboard-action" type="submit" disabled={!canUpload}>
          {isBusy ? 'Uploading...' : 'Upload'}
        </button>
        <button
          className="button button-secondary"
          type="button"
          onClick={resetUpload}
          disabled={isBusy || (!file && !error)}
        >
          Clear
        </button>
      </div>
    </form>
  )
}

export default VideoUploadCard
