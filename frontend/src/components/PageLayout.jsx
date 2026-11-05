import Navigation from './Navigation'
import Footer from './Footer'
import './PageLayout.css'

/**
 * PageLayout component - consistent page wrapper with navigation and footer
 *
 * @param {string} title - page title
 * @param {React.ReactNode} children - page content
 * @param {React.ReactNode} headerActions - optional actions in header
 * @param {string} className - optional additional CSS class for the page-layout wrapper
 */
export default function PageLayout({ title, children, headerActions, className }) {
  return (
    <div className={`page-layout ${className || ''}`}>
      <Navigation />
      <div className="container page-layout-body">
        {title && (
          <div className="page-header">
            <h1>{title}</h1>
            {headerActions && <div className="page-header-actions">{headerActions}</div>}
          </div>
        )}
        <div className="page-content">
          {children}
        </div>
      </div>
      <Footer />
    </div>
  )
}
