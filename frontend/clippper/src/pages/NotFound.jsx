import { Link } from 'react-router-dom'

function NotFound() {
  return (
    <main className="centered-page">
      <div>
        <span className="brand">
          Clip<b>pp</b>er
        </span>
        <h1>There's nothing here.</h1>
        <p>Whatever you were after has moved, or it never existed. Your clips are where you left them.</p>
        <Link className="button button-primary" to="/">
          Back to your clips
        </Link>
      </div>
    </main>
  )
}

export default NotFound
