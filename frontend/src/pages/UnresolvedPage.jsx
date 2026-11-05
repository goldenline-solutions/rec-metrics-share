import { useState, useEffect } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import UserMenu from '../components/UserMenu'
import { getUnresolvedGames, confirmGamePlayer, getMyClaims } from '../utils/api'
import './UnresolvedPage.css'

function UnresolvedPage() {
  const [unresolved, setUnresolved] = useState([])
  const [claims, setClaims] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [processing, setProcessing] = useState(new Set())
  const navigate = useNavigate()

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      setLoading(true)
      setError(null)
      const [unresolvedData, claimsData] = await Promise.all([
        getUnresolvedGames(),
        getMyClaims()
      ])
      setUnresolved(unresolvedData)
      setClaims(claimsData.filter(c => c.status === 'verified'))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleConfirm = async (gameId, gamePlayerId, action, claimId = null) => {
    const key = `${gameId}-${gamePlayerId}`
    if (processing.has(key)) return

    try {
      setProcessing(new Set([...processing, key]))
      setError(null)
      await confirmGamePlayer(gameId, gamePlayerId, action, claimId)
      await loadData()
    } catch (err) {
      setError(err.message)
    } finally {
      setProcessing(new Set([...Array.from(processing).filter(k => k !== key)]))
    }
  }

  const handleViewGame = (gameId) => {
    navigate(`/games/${gameId}`)
  }

  return (
    <div className="container">
      <div className="page-header">
        <div className="page-header-content">
          <h1>Unresolved Games</h1>
          <nav>
            <NavLink to="/" end>Upload</NavLink>
            <NavLink to="/games">Games List</NavLink>
            <NavLink to="/stats">Stats</NavLink>
            <NavLink to="/leaderboard">Leaderboard</NavLink>
          </nav>
        </div>
        <UserMenu />
      </div>

      <div className="unresolved-page-content">
        {error && (
          <div className="error-message">
            {error}
          </div>
        )}

        {loading ? (
          <div className="loading">Loading unresolved games...</div>
        ) : unresolved.length === 0 ? (
          <div className="empty-state">
            <p>No unresolved games found.</p>
            <p>All detected player names have been resolved or don't match your verified claims.</p>
          </div>
        ) : (
          <div className="unresolved-list">
            {unresolved.map((item) => {
              const key = `${item.game_id}-${item.game_player_id}`
              const isProcessing = processing.has(key)
              const verifiedClaim = claims.find(c => c.player_id === item.player_id_identity)

              return (
                <div key={key} className="unresolved-card">
                  <div className="unresolved-header">
                    <h3>Detected Name: {item.detected_raw_name}</h3>
                    {item.suggested_match && (
                      <span className="suggested-badge">Suggested Match</span>
                    )}
                  </div>
                  <div className="unresolved-details">
                    <p><strong>Normalized:</strong> {item.detected_norm_name}</p>
                    <p><strong>Match Method:</strong> {item.match_method || 'none'}</p>
                    {item.match_confidence !== null && (
                      <p><strong>Confidence:</strong> {item.match_confidence}%</p>
                    )}
                    <p><strong>Game Date:</strong> {new Date(item.game_created_at).toLocaleDateString()}</p>
                    {verifiedClaim && (
                      <p className="verified-claim-info">
                        <strong>Verified Claim:</strong> {verifiedClaim.display_name}
                      </p>
                    )}
                  </div>
                  <div className="unresolved-actions">
                    <button
                      onClick={() => handleConfirm(item.game_id, item.game_player_id, 'me', verifiedClaim?.id)}
                      disabled={isProcessing}
                      className="btn btn-primary"
                    >
                      {isProcessing ? 'Processing...' : "That's Me"}
                    </button>
                    <button
                      onClick={() => handleConfirm(item.game_id, item.game_player_id, 'not_me')}
                      disabled={isProcessing}
                      className="btn btn-secondary"
                    >
                      {isProcessing ? 'Processing...' : 'Not Me'}
                    </button>
                    <button
                      onClick={() => handleViewGame(item.game_id)}
                      className="btn btn-outline"
                    >
                      View Game
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default UnresolvedPage

