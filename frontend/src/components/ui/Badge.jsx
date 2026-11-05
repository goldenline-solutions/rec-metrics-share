import './Badge.css'

/**
 * Badge component - small status indicator
 * 
 * @param {string} variant - 'default' | 'positive' | 'negative' | 'warning'
 * @param {React.ReactNode} children - badge content
 * @param {string} className - additional CSS classes
 */
export default function Badge({ variant = 'default', children, className = '' }) {
  return (
    <span className={`badge badge-${variant} ${className}`}>
      {children}
    </span>
  )
}
