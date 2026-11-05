import { NavLink } from 'react-router-dom'
import './SectionTabs.css'

/**
 * SectionTabs component - routed tab bar for a multi-page section
 *
 * Each tab is a NavLink, so the section's views keep their own URLs and stay
 * deep-linkable, shareable and back-button friendly — unlike state-driven tabs.
 *
 * @param {Array<{to: string, label: string, end?: boolean}>} tabs - tab definitions
 * @param {string} ariaLabel - accessible name for the tab list
 */
export default function SectionTabs({ tabs, ariaLabel = 'Section' }) {
  return (
    <nav className="section-tabs" aria-label={ariaLabel}>
      {tabs.map(({ to, label, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) => `section-tab ${isActive ? 'active' : ''}`}
        >
          {label}
        </NavLink>
      ))}
    </nav>
  )
}
