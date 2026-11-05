import './Button.css'

/**
 * Button component - reusable button with variants
 * 
 * @param {string} variant - 'primary' | 'outline' | 'ghost'
 * @param {string} size - 'sm' | 'md' | 'lg'
 * @param {boolean} disabled - disabled state
 * @param {React.ReactNode} children - button content
 * @param {object} props - other button props
 */
export default function Button({ 
  variant = 'primary', 
  size = 'md', 
  children, 
  className = '',
  ...props 
}) {
  return (
    <button 
      className={`btn btn-${variant} btn-${size} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}
