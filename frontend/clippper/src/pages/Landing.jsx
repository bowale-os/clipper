import { SignInButton, SignUpButton, useAuth } from '@clerk/react'
import { Navigate } from 'react-router-dom'
import Poster from '../components/Poster'

// The same poster the signed-in app builds, so the landing shows the actual
// thing you get back rather than an illustration of it.
const previewClips = [
  { title: 'The clutch 1v4', length: '0:49' },
  { title: 'Patch notes rant', length: '0:38' },
  { title: 'Chat catches it', length: '0:52' },
]

function Landing() {
  const { isLoaded, isSignedIn } = useAuth()

  if (!isLoaded) {
    return null
  }

  if (isSignedIn) {
    return <Navigate to="/" replace />
  }

  return (
    <main className="landing">
      <div className="landing-left">
        <span className="brand">
          Clip<b>pp</b>er
        </span>

        <div className="landing-clips" aria-hidden="true">
          {previewClips.map((clip) => (
            <figure className="landing-clip" key={clip.title}>
              <Poster caption={clip.title} showFormat={false} />
              <figcaption>
                <span className="mono">{clip.length}</span>
                <span className="landing-clip-tag">Ready to post</span>
              </figcaption>
            </figure>
          ))}
        </div>

        <p>
          Upload once. Get back <b>the moments worth posting</b>, with captions already on.
        </p>
      </div>

      <div className="landing-right">
        <p className="landing-kicker">For streamers with a day job</p>
        <h1>
          A week of streams. <b>Twenty clips.</b> In One sitting.
        </h1>

        <SignUpButton mode="modal" forceRedirectUrl="/" fallbackRedirectUrl="/">
          <button className="auth-button" type="button">
            Create an account
          </button>
        </SignUpButton>

        <div className="auth-or">or</div>

        <SignInButton mode="modal" forceRedirectUrl="/" fallbackRedirectUrl="/">
          <button className="auth-button is-ghost" type="button">
            Sign in
          </button>
        </SignInButton>

        <p className="legal">
          By continuing you agree to our <a href="/terms">Terms</a> and{' '}
          <a href="/privacy">Privacy Policy</a>.
        </p>
      </div>
    </main>
  )
}

export default Landing
