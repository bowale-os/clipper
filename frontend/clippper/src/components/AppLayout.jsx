import { UserButton, useUser } from '@clerk/react'
import { NavLink } from 'react-router-dom'
import ThemeToggle from './ThemeToggle'
import { HomeIcon, LibraryIcon } from './icons'

const navItems = [
  { label: 'Dashboard', to: '/dashboard', Icon: HomeIcon },
  { label: 'Library', to: '/videos', Icon: LibraryIcon },
]

function navClass({ isActive }) {
  return isActive ? 'sidebar-link active' : 'sidebar-link'
}

function Brand() {
  return (
    <a className="brand" href="/dashboard" aria-label="Clippper home">
      <span className="brand-mark">C</span>
      <span>Clippper</span>
    </a>
  )
}

/**
 * Desktop: fixed left sidebar. Mobile (<=768px): top bar + bottom tab bar,
 * so the primary nav stays thumb-reachable.
 */
function AppLayout({ children, eyebrow, title, actions }) {
  const { isLoaded, user } = useUser()
  const displayName = user?.firstName || user?.fullName || 'Account'

  return (
    <div className="app-layout">
      <aside className="app-sidebar">
        <Brand />

        <nav className="sidebar-nav" aria-label="Main">
          {navItems.map(({ label, to, Icon }) => (
            <NavLink className={navClass} end key={label} to={to}>
              <Icon />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-account">
            <UserButton />
            <span>{isLoaded ? displayName : 'Account'}</span>
          </div>
          <ThemeToggle />
        </div>
      </aside>

      <header className="app-mobile-bar">
        <Brand />
        <div className="app-mobile-bar-actions">
          <ThemeToggle />
          <UserButton />
        </div>
      </header>

      <main className="app-main">
        <div className="app-content">
          {title ? (
            <div className="page-header">
              <div>
                {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
                <h1>{title}</h1>
              </div>
              {actions ? <div className="page-header-actions">{actions}</div> : null}
            </div>
          ) : null}

          {children}
        </div>
      </main>

      <nav className="app-tabbar" aria-label="Main">
        {navItems.map(({ label, to, Icon }) => (
          <NavLink className={navClass} end key={label} to={to}>
            <Icon />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

export default AppLayout
