import { useState, useRef } from 'react'
import { toPng } from 'html-to-image'
import './ShareableStatCard.css'

/**
 * Shareable stat card component with copy link and PNG download functionality.
 */
function ShareableStatCard({ shareCard }) {
  const [copied, setCopied] = useState(false)
  const cardRef = useRef(null)

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy link:', err)
      alert('Failed to copy link. Please copy the URL manually.')
    }
  }

  const handleDownloadPNG = async () => {
    if (!cardRef.current) {
      console.error('Card ref not available')
      return
    }

    try {
      const dataUrl = await toPng(cardRef.current, {
        quality: 1.0,
        pixelRatio: 2,
        backgroundColor: 'var(--color-surface-1)'
      })
      
      const link = document.createElement('a')
      link.download = `stat-card-${Date.now()}.png`
      link.href = dataUrl
      link.click()
    } catch (err) {
      console.error('Failed to generate PNG:', err)
      alert('Failed to download image. Please try again.')
    }
  }

  if (!shareCard) {
    return null
  }

  return (
    <div className="shareable-stat-card-container">
      <div 
        ref={cardRef}
        className="shareable-stat-card"
        style={{ cursor: 'default' }}
      >
        <div className="stat-card-headline">{shareCard.headline}</div>
        <div className="stat-card-stat">{shareCard.stat}</div>
        <div className="stat-card-text">{shareCard.text}</div>
        {shareCard.footnote && (
          <div className="stat-card-footnote">{shareCard.footnote}</div>
        )}
      </div>
      
      <div className="stat-card-actions">
        <button 
          onClick={handleCopyLink}
          className="stat-card-button stat-card-button-link"
        >
          {copied ? '✓ Copied!' : 'Copy Link'}
        </button>
        <button 
          onClick={handleDownloadPNG}
          className="stat-card-button stat-card-button-download"
        >
          Download PNG
        </button>
      </div>
    </div>
  )
}

export default ShareableStatCard

