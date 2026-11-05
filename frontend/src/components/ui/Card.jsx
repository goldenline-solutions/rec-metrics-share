import './Card.css'

/**
 * Card component - container for content sections
 * 
 * @param {React.ReactNode} children - card content
 * @param {string} className - additional CSS classes
 * @param {object} props - other div props
 */
export default function Card({ children, className = '', ...props }) {
  return (
    <div className={`card ${className}`} {...props}>
      {children}
    </div>
  )
}
