import './MetricCard.css'

/**
 * MetricCard component - displays a single metric with label
 * 
 * @param {string} label - metric label
 * @param {string|number} value - metric value
 * @param {string} subtitle - optional subtitle
 * @param {string} className - additional CSS classes
 */
export default function MetricCard({ label, value, subtitle, className = '' }) {
  return (
    <div className={`metric-card ${className}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {subtitle && <div className="metric-subtitle">{subtitle}</div>}
    </div>
  )
}
