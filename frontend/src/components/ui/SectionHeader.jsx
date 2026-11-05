import './SectionHeader.css'

/**
 * SectionHeader component - consistent section titles
 * 
 * @param {string} title - section title
 * @param {React.ReactNode} children - optional actions/children
 * @param {string} className - additional CSS classes
 */
export default function SectionHeader({ title, children, className = '' }) {
  return (
    <div className={`section-header ${className}`}>
      <h2 className="section-title">{title}</h2>
      {children && <div className="section-actions">{children}</div>}
    </div>
  )
}
