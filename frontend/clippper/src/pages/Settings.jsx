import { useAuth, useUser } from '@clerk/react'
import { useNavigate } from 'react-router-dom'
import TopBar from '../components/TopBar'
import FormatPicker from '../components/FormatPicker'
import Toggle from '../components/Toggle'
import { usePrefs } from '../hooks/usePrefs'

function Settings() {
  const { user } = useUser()
  const { signOut } = useAuth()
  const navigate = useNavigate()
  const { prefs, update } = usePrefs()

  async function handleSignOut() {
    await signOut()
    navigate('/', { replace: true })
  }

  return (
    <div className="app-shell">
      <div className="app-content">
        <TopBar showSettingsLink={false} />

        <div className="page-header">
          <div>
            <p className="eyebrow">Settings</p>
            <h1>All of it, on one page</h1>
          </div>
          <button className="button button-quiet" onClick={() => navigate('/')} type="button">
            Back to your clips
          </button>
        </div>

        <div className="settings-list">
          <div className="setting-row">
            <div>
              <b>Clip shape</b>
              <span className="setting-hint">What most of your clips come out as</span>
            </div>
            <FormatPicker onChange={(format) => update({ format })} value={prefs.format} />
          </div>

          <div className="setting-row">
            <div>
              <b>Captions</b>
              <span className="setting-hint">If you want them added automatically</span>
            </div>
            <Toggle
              ariaLabel="Captions"
              checked={prefs.captions}
              onChange={(captions) => update({ captions })}
            />
          </div>

          {/* Billing isn't wired up yet, so this row is a placeholder for the
              shape of it rather than a working control. */}
          <div className="setting-row">
            <div>
              <b>Plan</b>
              <span className="setting-hint">Billing is not switched on yet</span>
            </div>
            <button className="button button-primary button-small" disabled type="button">
              Upgrade
            </button>
          </div>

          <div className="setting-row">
            <div>
              <b>Account</b>
              <span className="setting-hint">
                {user?.primaryEmailAddress?.emailAddress || 'Signed in'}
              </span>
            </div>
            <button className="button button-quiet button-small" onClick={handleSignOut} type="button">
              Sign out
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Settings
