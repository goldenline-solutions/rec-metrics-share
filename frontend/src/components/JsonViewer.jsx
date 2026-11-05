import { useState } from 'react'
import './JsonViewer.css'

/**
 * JsonViewer component - displays JSON data in a formatted, collapsible view
 * 
 * Props:
 * - data: object - the JSON data to display
 * - title: string - optional title for the viewer
 */
function JsonViewer({ data, title = 'JSON Data' }) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!data) {
    return <p>No data to display</p>
  }

  const jsonString = JSON.stringify(data, null, 2)

  return (
    <div className="json-viewer">
      <div className="json-viewer-header">
        <h3>{title}</h3>
        <button onClick={() => setIsExpanded(!isExpanded)}>
          {isExpanded ? 'Collapse' : 'Expand'}
        </button>
      </div>
      <div className={`json-viewer-content ${isExpanded ? 'expanded' : ''}`}>
        <pre>{jsonString}</pre>
      </div>
    </div>
  )
}

export default JsonViewer

