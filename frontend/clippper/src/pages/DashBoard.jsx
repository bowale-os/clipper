import { UserButton } from '@clerk/react'

const projects = [
  {
    title: 'Founder interview',
    source: '82 min podcast',
    status: 'Editing',
    clips: 7,
  },
  {
    title: 'Product walkthrough',
    source: '34 min demo',
    status: 'Ready',
    clips: 5,
  },
  {
    title: 'Live stream recap',
    source: '126 min stream',
    status: 'Queued',
    clips: 12,
  },
]

const clips = [
  {
    title: 'The opening hook',
    format: 'TikTok 9:16',
    time: '00:03:18 - 00:03:57',
    score: 98,
  },
  {
    title: 'Best objection answer',
    format: 'Reels 9:16',
    time: '00:24:11 - 00:25:02',
    score: 95,
  },
  {
    title: 'Clear takeaway',
    format: 'Shorts 9:16',
    time: '00:41:36 - 00:42:15',
    score: 92,
  },
]

function DashBoard() {
  return (
    <main className="dashboard-shell">
      <aside className="dashboard-sidebar" aria-label="Dashboard navigation">
        <a className="brand dashboard-brand" href="/" aria-label="Clippper home">
          <span className="brand-mark">C</span>
          <span>Clippper</span>
        </a>

        <nav className="dashboard-nav">
          <a className="dashboard-nav-link active" href="/dashboard">
            Dashboard
          </a>
          <a className="dashboard-nav-link" href="/dashboard">
            Projects
          </a>
          <a className="dashboard-nav-link" href="/dashboard">
            Clips
          </a>
          <a className="dashboard-nav-link" href="/dashboard">
            Settings
          </a>
        </nav>
      </aside>

      <section className="dashboard-main">
        <header className="dashboard-header">
          <div>
            <p className="eyebrow">Agent workspace</p>
            <h1>What should Clippper make today?</h1>
          </div>
          <div className="dashboard-account">
            <span>Account</span>
            <UserButton />
          </div>
        </header>

        <section className="dashboard-grid" aria-label="Dashboard overview">
          <div className="dashboard-panel agent-composer">
            <div>
              <p className="panel-label">New edit</p>
              <h2>Give the agent direction</h2>
            </div>
            <label className="upload-drop">
              <span className="upload-icon">+</span>
              <span>
                Drop a long-form video or paste a link
                <small>YouTube, podcast, webinar, stream, or raw upload</small>
              </span>
            </label>
            <textarea
              className="agent-input"
              defaultValue="Find the strongest hooks and make five vertical clips with captions, quick cuts, and clean title cards."
              aria-label="Editing instructions"
            />
            <button className="button button-primary dashboard-action" type="button">
              Start agent
            </button>
          </div>

          <div className="dashboard-panel metrics-panel">
            <article>
              <span>18</span>
              <p>Clips generated</p>
            </article>
            <article>
              <span>4.8h</span>
              <p>Video processed</p>
            </article>
            <article>
              <span>93</span>
              <p>Avg. clip score</p>
            </article>
          </div>

          <div className="dashboard-panel projects-panel">
            <div className="panel-heading">
              <div>
                <p className="panel-label">Active projects</p>
                <h2>In progress</h2>
              </div>
              <button className="button button-secondary" type="button">
                View all
              </button>
            </div>

            <div className="project-list">
              {projects.map((project) => (
                <article className="project-row" key={project.title}>
                  <div>
                    <h3>{project.title}</h3>
                    <p>{project.source}</p>
                  </div>
                  <span>{project.clips} clips</span>
                  <strong>{project.status}</strong>
                </article>
              ))}
            </div>
          </div>

          <div className="dashboard-panel clips-panel">
            <div className="panel-heading">
              <div>
                <p className="panel-label">Recent clips</p>
                <h2>Ready to review</h2>
              </div>
            </div>

            <div className="dashboard-clip-list">
              {clips.map((clip) => (
                <article className="dashboard-clip" key={clip.title}>
                  <span>{clip.score}</span>
                  <div>
                    <h3>{clip.title}</h3>
                    <p>
                      {clip.format} - {clip.time}
                    </p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>
      </section>
    </main>
  )
}

export default DashBoard
