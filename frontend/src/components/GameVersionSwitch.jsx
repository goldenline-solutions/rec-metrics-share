import { GAME_VERSIONS, useGameVersion } from '../contexts/GameVersionContext'
import './GameVersionSwitch.css'

/**
 * GameVersionSwitch - segmented 2K26 / 2K27 toggle
 *
 * Two real radios under the skin, so arrow keys move between titles and screen
 * readers announce the group. Writes to the shared GameVersion context, so
 * flipping it here changes every page that reads game data.
 *
 * @param {string} label - visible label before the switch
 * @param {string} className - additional CSS classes
 * @param {function} onChange - optional extra callback with the new version
 */
export default function GameVersionSwitch({ label = 'Game', className = '', onChange }) {
  const { gameVersion, setGameVersion } = useGameVersion()

  const handleChange = (version) => {
    setGameVersion(version)
    if (onChange) onChange(version)
  }

  return (
    <div className={`game-version-switch ${className}`}>
      {label && <span className="game-version-label">{label}:</span>}
      <div className="game-version-options" role="radiogroup" aria-label="NBA 2K title">
        {GAME_VERSIONS.map((version) => (
          <label
            key={version}
            className={`game-version-option ${gameVersion === version ? 'active' : ''}`}
          >
            <input
              type="radio"
              name="game-version"
              value={version}
              checked={gameVersion === version}
              onChange={() => handleChange(version)}
            />
            <span>{version}</span>
          </label>
        ))}
      </div>
    </div>
  )
}
