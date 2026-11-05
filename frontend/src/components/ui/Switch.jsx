import './Switch.css'

/**
 * Switch component - labelled on/off toggle
 *
 * A real checkbox under the skin, so it is keyboard operable and announced
 * correctly. Use for view options ("show unavailable"), not for submitting.
 *
 * @param {boolean} checked - current state
 * @param {function} onChange - called with the next boolean
 * @param {React.ReactNode} label - visible label text
 * @param {string} hint - optional secondary text after the label
 * @param {string} className - additional CSS classes
 */
export default function Switch({ checked, onChange, label, hint, className = '' }) {
  return (
    <label className={`switch ${className}`}>
      <input
        type="checkbox"
        className="switch-input"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="switch-track" aria-hidden="true">
        <span className="switch-thumb" />
      </span>
      <span className="switch-label">
        {label}
        {hint && <span className="switch-hint">{hint}</span>}
      </span>
    </label>
  )
}
