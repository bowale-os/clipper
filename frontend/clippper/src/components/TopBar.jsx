import { UserButton } from '@clerk/react'
import { Link } from 'react-router-dom'
import { SettingsIcon } from './icons'

function Brand() {
  return (
    <Link className="brand" to="/" aria-label="Clippper home">
      Clip<b>pp</b>er
    </Link>
  )
}

/**
 * The brand in the corner is the only label the signed-in app carries. There is
 * nowhere else to go, so there is no nav — just settings and the account menu.
 */
function TopBar({ showSettingsLink = true }) {
  return (
    <div className="app-top">
      <Brand />
      <div className="app-top-actions">
        {showSettingsLink ? (
          <Link className="icon-button" to="/settings" aria-label="Settings">
            <SettingsIcon size={17} />
          </Link>
        ) : null}
        <UserButton />
      </div>
    </div>
  )
}

export { Brand }
export default TopBar
