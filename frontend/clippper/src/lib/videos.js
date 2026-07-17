/* GET /videos/ returns videos pre-grouped by status. The UI shows one
   chronological grid with filters, so it gets flattened back out here. */

export const VIDEO_STATUSES = ['ready', 'processing', 'uploaded', 'uploading', 'error']

function asArray(value) {
  return Array.isArray(value) ? value : []
}

export function flattenVideos(data) {
  if (!data) {
    return []
  }

  return VIDEO_STATUSES.flatMap((status) => asArray(data[`${status}_videos`])).sort(
    (a, b) => new Date(b?.created_at || 0) - new Date(a?.created_at || 0),
  )
}

export function countByStatus(videos) {
  return videos.reduce((counts, video) => {
    const status = video?.status
    counts[status] = (counts[status] || 0) + 1
    return counts
  }, {})
}
