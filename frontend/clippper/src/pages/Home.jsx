import { Show, SignInButton, SignUpButton, UserButton, useAuth } from '@clerk/react'
import { Navigate } from 'react-router-dom'
import ThemeToggle from '../components/ThemeToggle'

// A flat mock of the moments screen — the real thing, not an illustration.
const previewMoments = [
  { score: 94, title: 'The clutch 1v4', time: '00:18:42 – 00:19:31' },
  { score: 88, title: 'Unhinged rant about patch notes', time: '00:36:08 – 00:36:47' },
  { score: 81, title: 'Chat catches the misplay', time: '01:04:13 – 01:05:02' },
]

function Home() {
  const { isLoaded, isSignedIn } = useAuth()

  if (!isLoaded) {
    return null
  }

  if (isSignedIn) {
    return <Navigate to="/dashboard" replace />
  }

  return (
    <main className="home-shell">
      <header className="home-topbar">
        <a className="brand" href="/" aria-label="Clippper home">
          <span className="brand-mark">C</span>
          <span>Clippper</span>
        </a>

        <div className="home-topbar-actions">
          <ThemeToggle />
          <Show when="signed-out">
            <SignInButton mode="modal" forceRedirectUrl="/dashboard" fallbackRedirectUrl="/dashboard">
              <button className="button button-ghost" type="button">
                Sign in
              </button>
            </SignInButton>
            <SignUpButton mode="modal" forceRedirectUrl="/dashboard" fallbackRedirectUrl="/dashboard">
              <button className="button button-primary" type="button">
                Sign up
              </button>
            </SignUpButton>
          </Show>

          <Show when="signed-in">
            <UserButton />
          </Show>
        </div>
      </header>

      <section className="hero" aria-labelledby="hero-title">
        <div>
          <p className="eyebrow">For streamers with a day job</p>
          <h1 id="hero-title">A week of streams. Ten clips. One sitting.</h1>
          <p className="hero-copy">
            Upload your stream and Clippper finds the moments worth posting, scores them, and renders
            them ready for TikTok, Reels, and Shorts. No timeline. We'll handle the boring stuff.
          </p>

          <Show when="signed-out">
            <div className="hero-actions" aria-label="Get started">
              <SignUpButton mode="modal" forceRedirectUrl="/dashboard" fallbackRedirectUrl="/dashboard">
                <button className="button button-large button-primary" type="button">
                  Start clipping free
                </button>
              </SignUpButton>
              <SignInButton mode="modal" forceRedirectUrl="/dashboard" fallbackRedirectUrl="/dashboard">
                <button className="button button-large button-secondary" type="button">
                  Sign in
                </button>
              </SignInButton>
            </div>
          </Show>

          <div className="hero-points">
            <span>Auto-scored moments</span>
            <span>Captions on by default</span>
            <span>9:16, 1:1, and 16:9</span>
          </div>
        </div>

        <div className="hero-preview" aria-label="Preview of detected moments">
          <div className="hero-preview-file">
            <span>saturday_ranked_grind.mp4</span>
            <span>4:12:08</span>
          </div>

          <div className="hero-preview-list">
            {previewMoments.map((moment) => (
              <article className="hero-preview-row" key={moment.title}>
                <span className="moment-score">{moment.score}</span>
                <div>
                  <h3>{moment.title}</h3>
                  <p>{moment.time}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>
    </main>
  )
}

export default Home
