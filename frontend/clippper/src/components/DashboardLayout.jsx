import { UserButton, useUser } from '@clerk/react'
import { NavLink } from 'react-router-dom'

const navItems = [
  { label: 'Dashboard', to: '/dashboard' },
  { label: 'Videos', to: '/videos' },
  { label: 'Clips', to: '/clips' },
  { label: 'Settings', to: '/settings' },
]

function DashboardLayout({ children, eyebrow = 'Agent workspace', title }) {
  const { isLoaded, user } = useUser()
  const displayName = user?.firstName || user?.fullName || 'Account'

  return (
    <main className="dashboard-shell">
      <aside className="dashboard-sidebar" aria-label="Dashboard navigation">
        <a className="brand dashboard-brand" href="/" aria-label="Clippper home">
          <span className="brand-mark">C</span>
          <span>Clippper</span>
        </a>

        <nav className="dashboard-nav">
          {navItems.map((item) => (
            <NavLink
              className={({ isActive }) =>
                isActive ? 'dashboard-nav-link active' : 'dashboard-nav-link'
              }
              end
              key={item.label}
              to={item.to}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <section className="dashboard-main">
        <header className="dashboard-header">
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
          </div>
          <div className="dashboard-account">
            <span>{isLoaded ? displayName : 'Account'}</span>
            <UserButton />
          </div>
        </header>

        {children}
      </section>
    </main>
  )
}

export default DashboardLayout
