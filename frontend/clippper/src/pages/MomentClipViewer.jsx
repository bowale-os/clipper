import { Link, useLocation, useParams } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import ClipRenderCard from '../components/ClipRenderCard'
import EmptyState from '../components/EmptyState'
import { ArrowLeftIcon } from '../components/icons'

function MomentClipViewer() {
  const { videoId, momentIndex } = useParams()
  const location = useLocation()
  const { clipId, startSec, endSec, format, captions, title } = location.state || {}
  const momentsPath = `/videos/${videoId}/moments`

  const backLink = (
    <Link className="button button-secondary" to={momentsPath}>
      <ArrowLeftIcon size={16} />
      Back to moments
    </Link>
  )

  // Route state is the only carrier for the clip id, so a refresh or a deep link
  // lands here empty.
  if (!clipId) {
    return (
      <AppLayout eyebrow="Clip" title="We lost track of this clip">
        <EmptyState
          action={backLink}
          description="Head back to the moments list and generate it again — it only takes a click."
          title="Nothing to show here"
        />
      </AppLayout>
    )
  }

  return (
    <AppLayout eyebrow="Clip" title={title || `Moment ${Number(momentIndex) + 1}`}>
      <div className="viewer-back">{backLink}</div>

      <div className="viewer-panel">
        <ClipRenderCard
          captions={captions}
          clipId={clipId}
          endSec={endSec}
          format={format}
          startSec={startSec}
        />
      </div>
    </AppLayout>
  )
}

export default MomentClipViewer
