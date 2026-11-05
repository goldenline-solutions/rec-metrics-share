import { useState } from 'react'
import { updateUserPlatform } from '../utils/api'
import './PlatformSelectionModal.css'

/**
 * PlatformSelectionModal - Modal to prompt user to select their platform (PC or Console)
 * 
 * Props:
 * - onPlatformSelected: function(platform) - called when platform is selected
 * - onClose: function() - called to close modal (optional, if user can skip)
 * - canSkip: boolean - whether user can skip/close without selecting (default: false)
 */
function PlatformSelectionModal({ onPlatformSelected, onClose, canSkip = false }) {
  const [selectedPlatform, setSelectedPlatform] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const handleSelect = async (platform) => {
    setSelectedPlatform(platform)
    setError(null)
    setSaving(true)

    try {
      await updateUserPlatform(platform)
      onPlatformSelected(platform)
    } catch (err) {
      setError(err.message || 'Failed to save platform selection')
      setSaving(false)
    }
  }

  return (
    <div className="platform-selection-overlay">
      <div className="platform-selection-modal">
        <h2>Select Your Platform</h2>
        <p>Please select the platform you play NBA 2K on. This helps us organize games and leaderboards.</p>
        
        <div className="platform-options">
          <button
            className={`platform-option ${selectedPlatform === 'PC' ? 'selected' : ''}`}
            onClick={() => handleSelect('PC')}
            disabled={saving}
          >
            <div className="platform-icon">💻</div>
            <div className="platform-name">PC</div>
          </button>
          
          <button
            className={`platform-option ${selectedPlatform === 'Console' ? 'selected' : ''}`}
            onClick={() => handleSelect('Console')}
            disabled={saving}
          >
            <div className="platform-icon">🎮</div>
            <div className="platform-name">Console</div>
          </button>
        </div>

        {error && (
          <div className="platform-error">
            {error}
          </div>
        )}

        {saving && (
          <div className="platform-saving">
            Saving...
          </div>
        )}

        {canSkip && onClose && (
          <button className="platform-skip" onClick={onClose}>
            Skip for now
          </button>
        )}
      </div>
    </div>
  )
}

export default PlatformSelectionModal
