import { useRef, useState } from 'react'
import { AuthExpiredError, ApiError, abortVideoUpload, uploadVideoFile } from '../services/api'
import { useAuthedApi } from './useAuthedApi'

const initialUploadState = {
  file: null,
  error: '',
  progress: 0,
  result: null,
  status: 'idle',
  autoDetect: false,
  contentType: 'default',
  resumeTarget: null,
}

function getReadableError(error) {
  if (error instanceof ApiError) {
    return error.message
  }

  if (error instanceof Error) {
    return error.message
  }

  return 'Something went wrong while uploading your video.'
}

function isVideoFile(file) {
  if (!file) {
    return false
  }

  if (file.type.startsWith('video/')) {
    return true
  }

  return /\.(mp4|mov|avi|mkv)$/i.test(file.name)
}

export function useVideoUpload({ resumeTarget: initialResumeTarget = null } = {}) {
  const { getFreshToken, handleExpiredAuth } = useAuthedApi()
  const [uploadState, setUploadState] = useState({
    ...initialUploadState,
    resumeTarget: initialResumeTarget,
  })
  const abortControllerRef = useRef(null)
  const activeVideoIdRef = useRef(null)

  const isBusy = ['initializing', 'uploading', 'completing'].includes(uploadState.status)

  function selectFile(file) {
    setUploadState((current) => {
      const kept = {
        resumeTarget: current.resumeTarget,
        autoDetect: current.autoDetect,
        contentType: current.contentType,
      }

      if (!file) {
        return { ...initialUploadState, ...kept }
      }

      if (!isVideoFile(file)) {
        return {
          ...initialUploadState,
          ...kept,
          error: 'Choose a video file: MP4, MOV, AVI, or MKV.',
          status: 'error',
        }
      }

      // Resumed parts are byte-offset slices, so the file must be byte-identical.
      if (current.resumeTarget && file.size !== current.resumeTarget.sizeBytes) {
        return {
          ...initialUploadState,
          ...kept,
          error: `This doesn't look like the same file — its size doesn't match "${current.resumeTarget.filename}".`,
          status: 'error',
        }
      }

      return {
        ...initialUploadState,
        ...kept,
        file,
        status: 'selected',
      }
    })
  }

  function startResume({ videoId, filename, sizeBytes }) {
    setUploadState({
      ...initialUploadState,
      resumeTarget: { videoId, filename, sizeBytes },
    })
  }

  function setAutoDetect(autoDetect) {
    setUploadState((current) => ({
      ...current,
      autoDetect,
    }))
  }

  function setContentType(contentType) {
    setUploadState((current) => ({
      ...current,
      contentType,
    }))
  }

  async function uploadSelectedFile() {
    if (!uploadState.file || isBusy) {
      return
    }

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      setUploadState((current) => ({
        ...current,
        error: '',
        progress: 0,
        result: null,
        status: 'initializing',
      }))

      const result = await uploadVideoFile({
        autoDetect: uploadState.autoDetect,
        contentType: uploadState.contentType,
        file: uploadState.file,
        getToken: getFreshToken,
        signal: controller.signal,
        resume: uploadState.resumeTarget ? { videoId: uploadState.resumeTarget.videoId } : undefined,
        onInit: ({ videoId }) => {
          activeVideoIdRef.current = videoId
        },
        onProgress: (progress) => {
          setUploadState((current) => ({
            ...current,
            progress,
          }))
        },
        onStepChange: (status) => {
          setUploadState((current) => ({
            ...current,
            status,
          }))
        },
      })

      setUploadState((current) => ({
        ...current,
        progress: 100,
        result,
        status: 'success',
        resumeTarget: null,
      }))
    } catch (error) {
      if (controller.signal.aborted) {
        // cancelUpload already reset the state; don't overwrite it with an error.
        return
      }

      if (error instanceof AuthExpiredError) {
        await handleExpiredAuth()
      }

      setUploadState((current) => ({
        ...current,
        error: getReadableError(error),
        status: 'error',
      }))
    } finally {
      abortControllerRef.current = null
      activeVideoIdRef.current = null
    }
  }

  async function cancelUpload() {
    abortControllerRef.current?.abort()
    const videoId = activeVideoIdRef.current
    // Aborting a resumed upload would delete the server row and the parts
    // already in R2, so only abort uploads this session started fresh.
    // (A resume that fell through to a fresh init gets a new video id.)
    const isResume = videoId && videoId === uploadState.resumeTarget?.videoId

    setUploadState((current) => ({
      ...initialUploadState,
      resumeTarget: current.resumeTarget,
      autoDetect: current.autoDetect,
      contentType: current.contentType,
    }))

    if (videoId && !isResume) {
      try {
        await abortVideoUpload({ videoId, getToken: getFreshToken })
      } catch {
        // The server row will be cleaned up from the videos list; cancelling stays silent.
      }
    }
  }

  function resetUpload() {
    // Clear the selection and any error, but stay in resume mode; the resume
    // target is only dropped after a successful upload or a fresh navigation.
    setUploadState((current) => ({
      ...initialUploadState,
      resumeTarget: current.resumeTarget,
      autoDetect: current.autoDetect,
      contentType: current.contentType,
    }))
  }

  return {
    ...uploadState,
    isBusy,
    cancelUpload,
    resetUpload,
    selectFile,
    setAutoDetect,
    setContentType,
    startResume,
    uploadSelectedFile,
  }
}
