import { Show, SignInButton, SignUpButton, UserButton, useAuth } from '@clerk/react'
import { Navigate } from 'react-router-dom'

function Home() {
  const { isLoaded, isSignedIn } = useAuth()

  if (!isLoaded) {
    return null
  }

  if (isLoaded && isSignedIn) {
    return <Navigate to="/dashboard" replace />
  }

  return (
    <main className="app-shell">
      <header className="top-bar">
        <a className="brand" href="/" aria-label="Clippper home">
          <span className="brand-mark">C</span>
          <span>Clippper</span>
        </a>

        <Show when="signed-out">
          <nav className="auth-actions" aria-label="Account">
            <SignInButton
              mode="modal"
              forceRedirectUrl="/dashboard"
              fallbackRedirectUrl="/dashboard"
            >
              <button className="button button-ghost" type="button">
                Sign in
              </button>
            </SignInButton>
            <SignUpButton
              mode="modal"
              forceRedirectUrl="/dashboard"
              fallbackRedirectUrl="/dashboard"
            >
              <button className="button button-primary" type="button">
                Sign up
              </button>
            </SignUpButton>
          </nav>
        </Show>

        <Show when="signed-in">
          <div className="user-menu">
            <UserButton />
          </div>
        </Show>
      </header>

      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy-block">
          <p className="eyebrow">Your video clipping agent</p>
          <h1 id="hero-title">Tell Clippper how to cut, edit, and shape your videos.</h1>
          <p className="hero-copy">
            Describe the clips you want from a podcast, stream, lesson, or
            interview. Clippper follows your direction, finds the right moments,
            and prepares edits for the formats you need.
          </p>

          <Show when="signed-out">
            <div className="hero-actions" aria-label="Get started">
              <SignUpButton
                mode="modal"
                forceRedirectUrl="/dashboard"
                fallbackRedirectUrl="/dashboard"
              >
                <button className="button button-large button-primary" type="button">
                  Start directing
                </button>
              </SignUpButton>
              <SignInButton
                mode="modal"
                forceRedirectUrl="/dashboard"
                fallbackRedirectUrl="/dashboard"
              >
                <button className="button button-large button-secondary" type="button">
                  Sign in
                </button>
              </SignInButton>
            </div>
          </Show>
        </div>

        <div className="clip-preview" aria-label="Agent editing preview">
          <div className="video-frame">
            <span className="play-dot" />
            <span className="video-title">Interview_final_82min.mp4</span>
            <span className="video-time">82:14</span>
          </div>

          <div className="agent-prompt">
            <span>Make three fast-paced clips for TikTok with captions and a strong hook.</span>
          </div>

          <div className="timeline" aria-hidden="true">
            <span className="track track-long" />
            <span className="clip-hit clip-hit-one" />
            <span className="clip-hit clip-hit-two" />
            <span className="clip-hit clip-hit-three" />
          </div>

          <div className="clip-list">
            <article className="clip-item">
              <span className="clip-score">98</span>
              <div>
                <h2>Hook-first edit</h2>
                <p>Captions, jump cuts, 00:18:42 - 00:19:31</p>
              </div>
            </article>
            <article className="clip-item">
              <span className="clip-score">94</span>
              <div>
                <h2>Contrarian take</h2>
                <p>Vertical crop, title card, 00:36:08 - 00:36:47</p>
              </div>
            </article>
            <article className="clip-item">
              <span className="clip-score">91</span>
              <div>
                <h2>Shareable lesson</h2>
                <p>Clean pauses, captions, 01:04:13 - 01:05:02</p>
              </div>
            </article>
          </div>
        </div>
      </section>
    </main>
  )
}

export default Home
