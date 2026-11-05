import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useVerifiedClaim } from '../hooks/useVerifiedClaim'
import { hasRole } from '../utils/api'
import UserMenu from './UserMenu'
import './Navigation.css'

/**
 * Navigation component - unified navigation bar
 *
 * Desktop: a single horizontal row.
 * Mobile (<=768px): the links move into an off-canvas drawer behind a menu
 * button. The previous behaviour stacked every link vertically in the header,
 * which pushed page content off the bottom of the first screen.
 */
export default function Navigation() {
  const { user } = useAuth()
  const { verifiedClaim } = useVerifiedClaim()
  const enableAnalytics = import.meta.env.VITE_ENABLE_ANALYTICS === 'true'

  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()
  const toggleRef = useRef(null)
  const drawerRef = useRef(null)

  // Navigating away should always close the drawer.
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  // While the drawer is open: lock body scroll, close on Escape, and keep
  // focus inside it. Restore focus to the toggle on close so keyboard users
  // don't get dropped at the top of the document.
  useEffect(() => {
    if (!menuOpen) return

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        setMenuOpen(false)
        toggleRef.current?.focus()
        return
      }
      if (e.key !== 'Tab' || !drawerRef.current) return
      const focusable = drawerRef.current.querySelectorAll(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    drawerRef.current?.querySelector('a, button')?.focus()

    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [menuOpen])

  const links = (
    <>
      <NavLink to="/" end>Home</NavLink>
      <NavLink to="/upload">Upload</NavLink>
      <NavLink to="/games">Games</NavLink>
      <NavLink to="/stats">Stats</NavLink>
      <NavLink to="/leaderboard">Leaderboard</NavLink>
      {user && <NavLink to="/league">League</NavLink>}
      {/* One entry for the whole Builder section — Planner, Templates and
          Builds are tabs inside it (see BuilderTabs). Points at the Planner
          (the default tab); the className keeps it highlighted on every
          /builds/* route, not just /builds/new. */}
      <NavLink
        to="/builds/new"
        className={() => (location.pathname === '/builds' || location.pathname.startsWith('/builds/') ? 'active' : undefined)}
      >
        Builder
      </NavLink>
      {verifiedClaim && (
        <NavLink to={`/players/${encodeURIComponent(verifiedClaim.display_name)}`}>
          My Profile
        </NavLink>
      )}
      {enableAnalytics && (
        <NavLink to="/analytics">Analytics</NavLink>
      )}
      {user && hasRole(user, 'admin') && (
        <NavLink to="/admin/builds">Admin</NavLink>
      )}
    </>
  )

  return (
    <nav className="navigation">
      <div className="navigation-content">
        <div className="navigation-left">
          <NavLink to="/" className="navigation-logo">
            <img src="/logo.png" alt="RecMetrics" className="navigation-logo-image" />
            RecMetrics
          </NavLink>
          <div className="navigation-links">{links}</div>
        </div>

        <div className="navigation-right">
          <UserMenu />
          <button
            type="button"
            ref={toggleRef}
            className="navigation-toggle"
            aria-expanded={menuOpen}
            aria-controls="navigation-drawer"
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span className={`navigation-toggle-bars ${menuOpen ? 'is-open' : ''}`} aria-hidden="true">
              <i></i><i></i><i></i>
            </span>
          </button>
        </div>
      </div>

      {/* Portalled to <body> on purpose. `.navigation` sets backdrop-filter,
          which — like transform — makes it the containing block for fixed
          descendants, so a drawer rendered inside it would be positioned
          against the header box instead of the viewport. */}
      {createPortal(
        <>
          {/* Scrim: clicking outside the drawer dismisses it. */}
          <div
            className={`navigation-scrim ${menuOpen ? 'is-open' : ''}`}
            onClick={() => setMenuOpen(false)}
            aria-hidden="true"
          />

          <div
            id="navigation-drawer"
            ref={drawerRef}
            className={`navigation-drawer ${menuOpen ? 'is-open' : ''}`}
            role="dialog"
            aria-modal="true"
            aria-label="Menu"
            {...(menuOpen ? {} : { inert: '' })}
          >
            <div className="navigation-drawer-links">{links}</div>
          </div>
        </>,
        document.body
      )}
    </nav>
  )
}
