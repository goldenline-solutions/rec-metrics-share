import './EmptyState.css'
import Button from './Button'

/**
 * EmptyState component - displays when no data is available
 * 
 * @param {string} title - empty state title
 * @param {string} message - empty state message
 * @param {React.ReactNode} action - optional action button/CTA
 * @param {string} className - additional CSS classes
 */
export default function EmptyState({ title, message, action, className = '' }) {
  return (
    <div className={`empty-state ${className}`}>
      <div className="empty-state-content">
        <h3 className="empty-state-title">{title}</h3>
        <p className="empty-state-message">{message}</p>
        {action && <div className="empty-state-action">{action}</div>}
      </div>
    </div>
  )
}
