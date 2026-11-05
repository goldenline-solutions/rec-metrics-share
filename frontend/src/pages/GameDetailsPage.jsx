import { useState, useEffect } from 'react'
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom'
import { fetchGameDetails, apiUrl, hasRole } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import BoxScoreSummary from '../components/BoxScoreSummary'
import PlayerTable from '../components/PlayerTable'
import MatchupsTable from '../components/MatchupsTable'
import JsonViewer from '../components/JsonViewer'
import GameEditModal from '../components/GameEditModal'
import PageLayout from '../components/PageLayout'
import Button from '../components/ui/Button'
import './GameDetailsPage.css'

function GameDetailsPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const { user } = useAuth()
  const returnToSearch = location.state?.returnToSearch ?? ''
  const [game, setGame] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [isEditModalOpen, setIsEditModalOpen] = useState(false)
  const [showJsonCard, setShowJsonCard] = useState(false)

  useEffect(() => {
    loadGameDetails()
  }, [id])

  const loadGameDetails = async () => {
    setLoading(true)
    setError(null)
    
    try {
      const data = await fetchGameDetails(id)
      setGame(data)
    } catch (err) {
      setError(err.message || 'Failed to load game details')
    } finally {
      setLoading(false)
    }
  }

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A'
    try {
      const date = new Date(dateString)
      return date.toLocaleString()
    } catch {
      return dateString
    }
  }

  if (loading) {
    return (
      <PageLayout title="Game Details" className="game-details-page">
        <div className="loading">Loading game details...</div>
      </PageLayout>
    )
  }

  if (error) {
    return (
      <PageLayout title="Game Details" className="game-details-page">
        <div className="error-message">
          <strong>Error:</strong> {error}
          <div style={{ marginTop: '15px' }}>
            <Button onClick={loadGameDetails}>Retry</Button>
            <Link to={`/games${returnToSearch}`}>
              <Button style={{ marginLeft: '10px' }}>Back to Games List</Button>
            </Link>
          </div>
        </div>
      </PageLayout>
    )
  }

  if (!game) {
    return (
      <PageLayout title="Game Details" className="game-details-page">
        <div className="error-message">Game not found</div>
      </PageLayout>
    )
  }

  const headerActions = hasRole(user, 'admin') && game ? (
    <Button 
      onClick={() => setIsEditModalOpen(true)}
      style={{
        padding: '8px 16px',
        fontSize: '14px'
      }}
    >
      Edit Game
    </Button>
  ) : null

  return (
    <PageLayout title="Game Details" headerActions={headerActions} className="game-details-page">
      <div className="game-details-content">
        <Link to={`/games${returnToSearch}`} className="game-details-back-link">
          ← Back to Games List
        </Link>
        {game.needs_verification && (
          <div className="warning-banner card" style={{
            backgroundColor: 'var(--color-warning-muted)',
            border: '2px solid var(--color-warning)',
            borderRadius: '8px',
            padding: '16px',
            marginBottom: '20px'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span style={{ fontSize: '24px' }}>⚠️</span>
              <div style={{ flex: 1 }}>
                <strong style={{ color: 'var(--color-warning)', fontSize: '16px' }}>
                  Data Needs Verification
                </strong>
                {game.warnings && game.warnings.length > 0 && (
                  <ul style={{ marginTop: '8px', marginBottom: 0, paddingLeft: '20px', color: 'var(--color-warning)' }}>
                    {game.warnings.map((warning, idx) => (
                      <li key={idx} style={{ marginBottom: '4px' }}>{warning}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="card">
          <h2 style={{ marginBottom: '15px' }}>Game Information</h2>
          <div className="game-info">
            <p><strong>Game ID:</strong> {game.game_id}</p>
            <p><strong>Created At:</strong> {formatDate(game.created_at)}</p>
            <p><strong>Platform:</strong> {game.platform || '—'}</p>
          </div>
        </div>

        {game.payload && (
          <>
          {game.screenshot_url && (
              <div className="card">
                <h2>Game Screenshot</h2>
                <div style={{
                  marginTop: 'var(--spacing-md)',
                  textAlign: 'center',
                  backgroundColor: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  padding: 'var(--spacing-md)',
                  borderRadius: 'var(--radius-md)'
                }}>
                  <img
                    src={apiUrl(game.screenshot_url)}
                    alt="Game screenshot"
                    style={{
                      maxWidth: '100%',
                      height: 'auto',
                      borderRadius: 'var(--radius-sm)'
                    }}
                  />
                </div>
              </div>
            )}
            <BoxScoreSummary payload={game.payload} />

            <div className="card">
              <h2>Player Statistics</h2>
              <PlayerTable 
                players={game.payload.players} 
                gameId={id} 
                isEditMode={isEditModalOpen}
              />
            </div>

            {game.payload.matchups && game.payload.matchups.length > 0 && (
              <div className="card">
                <h2>Positional Matchups</h2>
                <MatchupsTable matchups={game.payload.matchups} />
              </div>
            )}

            {/* {showJsonCard ? (
              <div className="card">
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '10px' }}>
                  <button 
                    onClick={() => setShowJsonCard(false)}
                    style={{
                      padding: '6px 12px',
                      backgroundColor: 'var(--color-text-secondary)',
                      color: 'white',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '12px'
                    }}
                  >
                    Hide JSON Card
                  </button>
                </div>
                <JsonViewer 
                  data={game.payload} 
                  title="Complete Game Data (JSON)"
                />
              </div>
            ) : (
              <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h2 style={{ margin: 0 }}>Complete Game Data (JSON)</h2>
                  <button 
                    onClick={() => setShowJsonCard(true)}
                    style={{
                      padding: '6px 12px',
                      backgroundColor: 'var(--color-text-secondary)',
                      color: 'white',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '12px'
                    }}
                  >
                    Show JSON Card
                  </button>
                </div>
              </div>
            )} */}


          </>
        )}
      </div>
      
      {isEditModalOpen && (
        <GameEditModal
          game={game}
          isOpen={isEditModalOpen}
          onClose={() => setIsEditModalOpen(false)}
          onSave={loadGameDetails}
          onDelete={() => navigate('/games')}
        />
      )}
    </PageLayout>
  )
}

export default GameDetailsPage

