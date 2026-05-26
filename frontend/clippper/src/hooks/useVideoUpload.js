import { useState } from 'react'
import { ApiError, uploadVideoFile } from '../services/api'
import { useAuthedApi } from './useAuthedApi'

const initialUploadState = {
  file: null,
  error: '',
  progress: 0,
  result: null,
  status: 'idle',
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

export function useVideoUpload() {
  const { runWithToken } = useAuthedApi()
  const [uploadState, setUploadState] = useState(initialUploadState)

  const isBusy = ['initializing', 'uploading', 'completing'].includes(uploadState.status)

  function selectFile(file) {
    if (!file) {
      setUploadState(initialUploadState)
      return
    }

    if (!isVideoFile(file)) {
      setUploadState({
        ...initialUploadState,
        error: 'Choose a video file: MP4, MOV, AVI, or MKV.',
        status: 'error',
      })
      return
    }

    setUploadState({
      ...initialUploadState,
      file,
      status: 'selected',
    })
  }

  async function uploadSelectedFile() {
    if (!uploadState.file || isBusy) {
      return
    }

    try {
      setUploadState((current) => ({
        ...current,
        error: '',
        progress: 0,
        result: null,
        status: 'initializing',
      }))

      const result = await runWithToken((token) =>
        uploadVideoFile({
          file: uploadState.file,
          token,
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
        }),
      )

      setUploadState((current) => ({
        ...current,
        progress: 100,
        result,
        status: 'success',
      }))
    } catch (error) {
      setUploadState((current) => ({
        ...current,
        error: getReadableError(error),
        status: 'error',
      }))
    }
  }

  function resetUpload() {
    setUploadState(initialUploadState)
  }

  return {
    ...uploadState,
    isBusy,
    resetUpload,
    selectFile,
    uploadSelectedFile,
  }
}
