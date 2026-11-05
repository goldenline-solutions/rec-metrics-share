/**
 * Simple SVG line chart component for displaying trends.
 * Takes an array of numbers and renders them as a line chart.
 */
function LineChart({ data, width = 300, height = 150, color = 'var(--color-accent)', label = '' }) {
  if (!data || data.length === 0) {
    return (
      <div style={{ width: '100%', maxWidth: width, height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-secondary)' }}>
        No data available
      </div>
    )
  }

  const padding = { top: 20, right: 20, bottom: 30, left: 40 }
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom

  // Calculate min/max for scaling
  const minValue = Math.min(...data)
  const maxValue = Math.max(...data)
  const range = maxValue - minValue || 1 // Avoid division by zero

  // Generate points
  const points = data.map((value, index) => {
    const x = padding.left + (index / (data.length - 1 || 1)) * chartWidth
    const y = padding.top + chartHeight - ((value - minValue) / range) * chartHeight
    return { x, y, value }
  })

  // Create path string for the line
  const pathData = points.map((point, index) => {
    return `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`
  }).join(' ')

  // Create area path (for fill)
  // The gradient needs a valid id, and `color` may be a var(--token) string.
  const gradientId = `gradient-${String(color).replace(/[^a-zA-Z0-9]/g, '')}`

  const areaPath = `${pathData} L ${points[points.length - 1].x} ${padding.top + chartHeight} L ${points[0].x} ${padding.top + chartHeight} Z`

  return (
    <div style={{ width: '100%', maxWidth: width }}>
      {label && (
        <div style={{ marginBottom: '8px', fontSize: '14px', fontWeight: 'var(--font-weight-medium)', color: 'var(--color-text-secondary)' }}>
          {label}
        </div>
      )}
      {/* viewBox carries the fixed coordinate space the geometry is computed in;
          width:100%/height:auto lets the chart scale down on narrow screens
          instead of forcing horizontal overflow. */}
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ display: 'block', width: '100%', height: 'auto' }}
      >
        {/* Grid lines */}
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0.05" />
          </linearGradient>
        </defs>
        
        {/* Y-axis grid lines */}
        {[0, 1, 2, 3, 4].map(i => {
          const y = padding.top + (i / 4) * chartHeight
          return (
            <line
              key={`grid-${i}`}
              x1={padding.left}
              y1={y}
              x2={padding.left + chartWidth}
              y2={y}
              stroke="var(--color-border)"
              strokeWidth="1"
            />
          )
        })}

        {/* Area fill */}
        <path
          d={areaPath}
          fill={`url(#${gradientId})`}
        />

        {/* Line */}
        <path
          d={pathData}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Data points */}
        {points.map((point, index) => (
          <circle
            key={index}
            cx={point.x}
            cy={point.y}
            r="3"
            fill={color}
            stroke="var(--color-bg)"
            strokeWidth="2"
          />
        ))}

        {/* Y-axis labels */}
        {[0, 1, 2, 3, 4].map(i => {
          const value = minValue + (range * (1 - i / 4))
          const y = padding.top + (i / 4) * chartHeight
          return (
            <text
              key={`y-label-${i}`}
              x={padding.left - 10}
              y={y + 4}
              textAnchor="end"
              fontSize="10"
              fill="var(--color-text-secondary)"
            >
              {Math.round(value)}
            </text>
          )
        })}

        {/* X-axis labels (game numbers) */}
        {points.map((point, index) => {
          if (index % Math.ceil(data.length / 5) === 0 || index === data.length - 1) {
            return (
              <text
                key={`x-label-${index}`}
                x={point.x}
                y={height - padding.bottom + 15}
                textAnchor="middle"
                fontSize="10"
                fill="var(--color-text-secondary)"
              >
                {data.length - index}
              </text>
            )
          }
          return null
        })}
      </svg>
    </div>
  )
}

export default LineChart

