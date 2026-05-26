import DashboardLayout from '../components/DashboardLayout'
import VideoUploadCard from '../components/VideoUploadCard'

function DashBoard() {
  return (
    <DashboardLayout title="Upload a video for Clippper to work on.">
      <section className="dashboard-upload-layout" aria-label="Video upload workspace">
        <VideoUploadCard />

        <aside className="dashboard-panel upload-guide">
          <p className="panel-label">Upload flow</p>
          <h2>What happens next</h2>
          <ol>
            <li>
              <strong>Initialize</strong>
              <span>Clippper creates a video record and secure upload URL.</span>
            </li>
            <li>
              <strong>Upload</strong>
              <span>Your browser sends the file directly to storage.</span>
            </li>
            <li>
              <strong>Complete</strong>
              <span>The backend marks the video as ready for processing.</span>
            </li>
          </ol>
        </aside>
      </section>
    </DashboardLayout>
  )
}

export default DashBoard
