import { useState, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { searchPlayer } from '../utils/api'
import PageLayout from '../components/PageLayout'
import GameVersionSwitch from '../components/GameVersionSwitch'
import { useGameVersion } from '../contexts/GameVersionContext'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import MetricCard from '../components/ui/MetricCard'
import SectionHeader from '../components/ui/SectionHeader'
import EmptyState from '../components/ui/EmptyState'
import Seo from '../components/Seo'
import './PlayerStatsPage.css'

function PlayerStatsPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { gameVersion } = useGameVersion()
  const [searchQuery, setSearchQuery] = useState('')
  const [playerData, setPlayerData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Check for query parameter on mount
  useEffect(() => {
    const q = searchParams.get('q')
    if (q) {
      setSearchQuery(q)
      handleSearchFromQuery(q)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const handleSearchFromQuery = async (query) => {
    setLoading(true)
    setError(null)
    setPlayerData(null)

    try {
      const data = await searchPlayer(query.trim(), 'ALL', 1, 25, gameVersion)
      
      if (data.player) {
        // Redirect to profile page
        navigate(`/players/${encodeURIComponent(data.player.gamertag)}`)
        return
      } else {
        setError(data.message || 'No player found')
      }
    } catch (err) {
      setError(err.message || 'Failed to search for player')
      setPlayerData(null)
    } finally {
      setLoading(false)
    }
  }

  const handleSearch = async (e) => {
    e.preventDefault()
    
    if (!searchQuery.trim()) {
      setError('Please enter a player name to search')
      return
    }

    setLoading(true)
    setError(null)
    setPlayerData(null)

    try {
      const data = await searchPlayer(searchQuery.trim(), 'ALL', 1, 25, gameVersion)
      
      if (data.player) {
        // Redirect to profile page
        navigate(`/players/${encodeURIComponent(data.player.gamertag)}`)
        return
      } else {
        setError(data.message || 'No player found')
      }
    } catch (err) {
      setError(err.message || 'Failed to search for player')
      setPlayerData(null)
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

  return (
    <PageLayout title="Player Statistics">
      <Seo
        title="NBA 2K26 REC Player Stats | RecMetrics"
        description="Search NBA 2K26 REC player statistics and role-based performance grades. Find any tracked player and view their game logs."
        path="/stats"
      />
      <div className="player-stats-content">
        <Card className="search-section">
          <SectionHeader title="Search Player" />
          <GameVersionSwitch className="stats-version-switch" />
          <form onSubmit={handleSearch} className="search-form">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Enter player gamertag..."
              className="search-input"
              disabled={loading}
            />
            <Button type="submit" disabled={loading || !searchQuery.trim()}>
              {loading ? 'Searching...' : 'Search'}
            </Button>
          </form>

          {error && (
            <div className="error-message" style={{ marginTop: 'var(--spacing-md)' }}>
              {error}
            </div>
          )}
        </Card>

        {playerData && playerData.player && (
          <>
            <Card className="player-header">
              <h2>{playerData.player.gamertag}</h2>
              {playerData.combined_players && playerData.combined_players > 1 && (
                <p className="match-note">
                  Combined {playerData.combined_players} player records with different capitalization:
                  {' '}
                  {playerData.player.variant_gamertags?.join(', ')}
                </p>
              )}
            </Card>

            {playerData.aggregated_stats && (
              <Card>
                <SectionHeader title="Career Statistics" />
                <div className="stats-grid">
                  <MetricCard 
                    label="Games"
                    value={playerData.aggregated_stats.games_played}
                  />
                  
                  <MetricCard 
                    label="Points"
                    value={playerData.aggregated_stats.pts}
                    subtitle={playerData.aggregated_stats.avg_pts !== undefined ? `${playerData.aggregated_stats.avg_pts} per game` : null}
                  />
                  
                  <MetricCard 
                    label="Rebounds"
                    value={playerData.aggregated_stats.reb}
                    subtitle={playerData.aggregated_stats.avg_reb !== undefined ? `${playerData.aggregated_stats.avg_reb} per game` : null}
                  />
                  
                  <MetricCard 
                    label="Assists"
                    value={playerData.aggregated_stats.ast}
                    subtitle={playerData.aggregated_stats.avg_ast !== undefined ? `${playerData.aggregated_stats.avg_ast} per game` : null}
                  />
                  
                  <MetricCard 
                    label="Steals"
                    value={playerData.aggregated_stats.stl}
                    subtitle={playerData.aggregated_stats.avg_stl !== undefined ? `${playerData.aggregated_stats.avg_stl} per game` : null}
                  />
                  
                  <MetricCard 
                    label="Blocks"
                    value={playerData.aggregated_stats.blk}
                    subtitle={playerData.aggregated_stats.avg_blk !== undefined ? `${playerData.aggregated_stats.avg_blk} per game` : null}
                  />
                  
                  <MetricCard 
                    label="Turnovers"
                    value={playerData.aggregated_stats.tov}
                    subtitle={playerData.aggregated_stats.avg_tov !== undefined ? `${playerData.aggregated_stats.avg_tov} per game` : null}
                  />
                  
                  <MetricCard 
                    label="Field Goals"
                    value={`${playerData.aggregated_stats.fgm}/${playerData.aggregated_stats.fga}`}
                    subtitle={playerData.aggregated_stats.fg_pct !== undefined ? `${playerData.aggregated_stats.fg_pct}%` : null}
                  />
                  
                  <MetricCard 
                    label="3-Pointers"
                    value={`${playerData.aggregated_stats.tpm}/${playerData.aggregated_stats.tpa}`}
                    subtitle={playerData.aggregated_stats.tp_pct !== undefined ? `${playerData.aggregated_stats.tp_pct}%` : null}
                  />
                  
                  <MetricCard 
                    label="Free Throws"
                    value={`${playerData.aggregated_stats.ftm}/${playerData.aggregated_stats.fta}`}
                    subtitle={playerData.aggregated_stats.ft_pct !== undefined ? `${playerData.aggregated_stats.ft_pct}%` : null}
                  />
                </div>
              </Card>
            )}

            {playerData.position_stats && Object.keys(playerData.position_stats).length > 0 && (
              <Card>
                <SectionHeader title="Statistics by Position" />
                <div className="position-stats-grid">
                  {Object.entries(playerData.position_stats).map(([position, stats]) => (
                    <div key={position} className="position-stat-card">
                      <h3 className="position-title">{position}</h3>
                      <div className="position-stat-content">
                        <div className="position-stat-row">
                          <span className="position-stat-label">Games:</span>
                          <span className="position-stat-value">{stats.games_played}</span>
                        </div>
                        
                        <div className="position-stat-row">
                          <span className="position-stat-label">Points:</span>
                          <span className="position-stat-value">
                            {stats.pts} total
                            {stats.avg_pts !== undefined && (
                              <span className="position-stat-avg"> ({stats.avg_pts} avg)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="position-stat-row">
                          <span className="position-stat-label">Rebounds:</span>
                          <span className="position-stat-value">
                            {stats.reb} total
                            {stats.avg_reb !== undefined && (
                              <span className="position-stat-avg"> ({stats.avg_reb} avg)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="position-stat-row">
                          <span className="position-stat-label">Assists:</span>
                          <span className="position-stat-value">
                            {stats.ast} total
                            {stats.avg_ast !== undefined && (
                              <span className="position-stat-avg"> ({stats.avg_ast} avg)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="position-stat-row">
                          <span className="position-stat-label">Steals:</span>
                          <span className="position-stat-value">
                            {stats.stl} total
                            {stats.avg_stl !== undefined && (
                              <span className="position-stat-avg"> ({stats.avg_stl} avg)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="position-stat-row">
                          <span className="position-stat-label">Blocks:</span>
                          <span className="position-stat-value">
                            {stats.blk} total
                            {stats.avg_blk !== undefined && (
                              <span className="position-stat-avg"> ({stats.avg_blk} avg)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="position-stat-row">
                          <span className="position-stat-label">Turnovers:</span>
                          <span className="position-stat-value">
                            {stats.tov} total
                            {stats.avg_tov !== undefined && (
                              <span className="position-stat-avg"> ({stats.avg_tov} avg)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="position-stat-row">
                          <span className="position-stat-label">FG:</span>
                          <span className="position-stat-value">
                            {stats.fgm}/{stats.fga}
                            {stats.fg_pct !== undefined && (
                              <span className="position-stat-avg"> ({stats.fg_pct}%)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="position-stat-row">
                          <span className="position-stat-label">3PT:</span>
                          <span className="position-stat-value">
                            {stats.tpm}/{stats.tpa}
                            {stats.tp_pct !== undefined && (
                              <span className="position-stat-avg"> ({stats.tp_pct}%)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="position-stat-row">
                          <span className="position-stat-label">FT:</span>
                          <span className="position-stat-value">
                            {stats.ftm}/{stats.fta}
                            {stats.ft_pct !== undefined && (
                              <span className="position-stat-avg"> ({stats.ft_pct}%)</span>
                            )}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {playerData.defensive_stats && (
              <Card>
                <SectionHeader title="Defensive Statistics" />
                <div className="defensive-stats-grid">
                  <div className="defensive-stat-group">
                    <h3>Matchups</h3>
                    <div className="defensive-stat-value">{playerData.defensive_stats.matchups}</div>
                  </div>
                  
                  <div className="defensive-stat-group">
                    <h3>Opponent Points</h3>
                    <div className="defensive-stat-value">
                      {playerData.defensive_stats.opponent_pts} total
                      {playerData.defensive_stats.avg_opponent_pts !== undefined && (
                        <span className="defensive-stat-avg">({playerData.defensive_stats.avg_opponent_pts} avg)</span>
                      )}
                    </div>
                  </div>
                  
                  <div className="defensive-stat-group">
                    <h3>Opponent FG%</h3>
                    <div className="defensive-stat-value">
                      {playerData.defensive_stats.opponent_fgm}/{playerData.defensive_stats.opponent_fga}
                      {playerData.defensive_stats.opponent_fg_pct !== undefined && (
                        <span className="defensive-stat-avg">({playerData.defensive_stats.opponent_fg_pct}%)</span>
                      )}
                    </div>
                    {playerData.defensive_stats.opponent_normal_fg_pct !== undefined && playerData.defensive_stats.opponent_normal_fg_pct !== null && (
                      <div className="defensive-stat-comparison">
                        Normal: {playerData.defensive_stats.opponent_normal_fg_pct}%
                        {playerData.defensive_stats.fg_pct_difference !== undefined && playerData.defensive_stats.fg_pct_difference !== null && (
                          <span className={playerData.defensive_stats.fg_pct_difference < 0 ? "defensive-stat-good" : "defensive-stat-bad"}>
                            {' '}({playerData.defensive_stats.fg_pct_difference > 0 ? '+' : ''}{playerData.defensive_stats.fg_pct_difference}%)
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  
                  <div className="defensive-stat-group">
                    <h3>Opponent 3PT%</h3>
                    <div className="defensive-stat-value">
                      {playerData.defensive_stats.opponent_tpm}/{playerData.defensive_stats.opponent_tpa}
                      {playerData.defensive_stats.opponent_tp_pct !== undefined && (
                        <span className="defensive-stat-avg">({playerData.defensive_stats.opponent_tp_pct}%)</span>
                      )}
                    </div>
                    {playerData.defensive_stats.opponent_normal_tp_pct !== undefined && playerData.defensive_stats.opponent_normal_tp_pct !== null && (
                      <div className="defensive-stat-comparison">
                        Normal: {playerData.defensive_stats.opponent_normal_tp_pct}%
                        {playerData.defensive_stats.tp_pct_difference !== undefined && playerData.defensive_stats.tp_pct_difference !== null && (
                          <span className={playerData.defensive_stats.tp_pct_difference < 0 ? "defensive-stat-good" : "defensive-stat-bad"}>
                            {' '}({playerData.defensive_stats.tp_pct_difference > 0 ? '+' : ''}{playerData.defensive_stats.tp_pct_difference}%)
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  
                  <div className="defensive-stat-group">
                    <h3>Opponent FT%</h3>
                    <div className="defensive-stat-value">
                      {playerData.defensive_stats.opponent_ftm}/{playerData.defensive_stats.opponent_fta}
                      {playerData.defensive_stats.opponent_ft_pct !== undefined && (
                        <span className="defensive-stat-avg">({playerData.defensive_stats.opponent_ft_pct}%)</span>
                      )}
                    </div>
                  </div>
                  
                  <div className="defensive-stat-group">
                    <h3>Opponent Assists</h3>
                    <div className="defensive-stat-value">
                      {playerData.defensive_stats.opponent_ast} total
                      {playerData.defensive_stats.avg_opponent_ast !== undefined && (
                        <span className="defensive-stat-avg">({playerData.defensive_stats.avg_opponent_ast} avg)</span>
                      )}
                    </div>
                  </div>
                  
                  <div className="defensive-stat-group">
                    <h3>Opponent Turnovers</h3>
                    <div className="defensive-stat-value">
                      {playerData.defensive_stats.opponent_tov} total
                      {playerData.defensive_stats.avg_opponent_tov !== undefined && (
                        <span className="defensive-stat-avg">({playerData.defensive_stats.avg_opponent_tov} avg)</span>
                      )}
                    </div>
                  </div>
                  
                  <div className="defensive-stat-group">
                    <h3>Steals</h3>
                    <div className="defensive-stat-value">
                      {playerData.defensive_stats.steals} total
                      {playerData.defensive_stats.avg_steals !== undefined && (
                        <span className="defensive-stat-avg">({playerData.defensive_stats.avg_steals} avg)</span>
                      )}
                    </div>
                  </div>
                  
                  <div className="defensive-stat-group">
                    <h3>Blocks</h3>
                    <div className="defensive-stat-value">
                      {playerData.defensive_stats.blocks} total
                      {playerData.defensive_stats.avg_blocks !== undefined && (
                        <span className="defensive-stat-avg">({playerData.defensive_stats.avg_blocks} avg)</span>
                      )}
                    </div>
                  </div>
                </div>
              </Card>
            )}

            {playerData.defensive_stats_by_position && Object.keys(playerData.defensive_stats_by_position).length > 0 && (
              <Card>
                <SectionHeader title="Defensive Statistics by Position" />
                <div className="defensive-position-stats-grid">
                  {Object.entries(playerData.defensive_stats_by_position).map(([position, stats]) => (
                    <div key={position} className="defensive-position-card">
                      <h3 className="defensive-position-title">{position}</h3>
                      <div className="defensive-position-content">
                        <div className="defensive-position-row">
                          <span className="defensive-position-label">Matchups:</span>
                          <span className="defensive-position-value">{stats.matchups}</span>
                        </div>
                        
                        <div className="defensive-position-row">
                          <span className="defensive-position-label">Opponent PTS:</span>
                          <span className="defensive-position-value">
                            {stats.opponent_pts} total
                            {stats.avg_opponent_pts !== undefined && (
                              <span className="defensive-position-avg"> ({stats.avg_opponent_pts} avg)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="defensive-position-row">
                          <span className="defensive-position-label">Opponent FG%:</span>
                          <span className="defensive-position-value">
                            {stats.opponent_fgm}/{stats.opponent_fga}
                            {stats.opponent_fg_pct !== undefined && (
                              <span className="defensive-position-avg"> ({stats.opponent_fg_pct}%)</span>
                            )}
                          </span>
                        </div>
                        {stats.opponent_normal_fg_pct !== undefined && stats.opponent_normal_fg_pct !== null && (
                          <div className="defensive-position-row defensive-position-comparison">
                            <span className="defensive-position-label">Normal FG%:</span>
                            <span className="defensive-position-value">
                              {stats.opponent_normal_fg_pct}%
                              {stats.fg_pct_difference !== undefined && stats.fg_pct_difference !== null && (
                                <span className={stats.fg_pct_difference < 0 ? "defensive-stat-good" : "defensive-stat-bad"}>
                                  {' '}({stats.fg_pct_difference > 0 ? '+' : ''}{stats.fg_pct_difference}%)
                                </span>
                              )}
                            </span>
                          </div>
                        )}
                        
                        <div className="defensive-position-row">
                          <span className="defensive-position-label">Opponent 3PT%:</span>
                          <span className="defensive-position-value">
                            {stats.opponent_tpm}/{stats.opponent_tpa}
                            {stats.opponent_tp_pct !== undefined && (
                              <span className="defensive-position-avg"> ({stats.opponent_tp_pct}%)</span>
                            )}
                          </span>
                        </div>
                        {stats.opponent_normal_tp_pct !== undefined && stats.opponent_normal_tp_pct !== null && (
                          <div className="defensive-position-row defensive-position-comparison">
                            <span className="defensive-position-label">Normal 3PT%:</span>
                            <span className="defensive-position-value">
                              {stats.opponent_normal_tp_pct}%
                              {stats.tp_pct_difference !== undefined && stats.tp_pct_difference !== null && (
                                <span className={stats.tp_pct_difference < 0 ? "defensive-stat-good" : "defensive-stat-bad"}>
                                  {' '}({stats.tp_pct_difference > 0 ? '+' : ''}{stats.tp_pct_difference}%)
                                </span>
                              )}
                            </span>
                          </div>
                        )}
                        
                        <div className="defensive-position-row">
                          <span className="defensive-position-label">Opponent AST:</span>
                          <span className="defensive-position-value">
                            {stats.opponent_ast} total
                            {stats.avg_opponent_ast !== undefined && (
                              <span className="defensive-position-avg"> ({stats.avg_opponent_ast} avg)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="defensive-position-row">
                          <span className="defensive-position-label">Opponent TOV:</span>
                          <span className="defensive-position-value">
                            {stats.opponent_tov} total
                            {stats.avg_opponent_tov !== undefined && (
                              <span className="defensive-position-avg"> ({stats.avg_opponent_tov} avg)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="defensive-position-row">
                          <span className="defensive-position-label">Steals:</span>
                          <span className="defensive-position-value">
                            {stats.steals} total
                            {stats.avg_steals !== undefined && (
                              <span className="defensive-position-avg"> ({stats.avg_steals} avg)</span>
                            )}
                          </span>
                        </div>
                        
                        <div className="defensive-position-row">
                          <span className="defensive-position-label">Blocks:</span>
                          <span className="defensive-position-value">
                            {stats.blocks} total
                            {stats.avg_blocks !== undefined && (
                              <span className="defensive-position-avg"> ({stats.avg_blocks} avg)</span>
                            )}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {playerData.games && playerData.games.length > 0 && (
              <Card>
                <SectionHeader title={`Games Played (${playerData.games.length})`} />
                <div className="games-table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Position</th>
                        <th>Team</th>
                        <th>Score</th>
                        <th>Opponent</th>
                        <th>PTS</th>
                        <th>REB</th>
                        <th>AST</th>
                        <th>STL</th>
                        <th>BLK</th>
                        <th>Grade</th>
                        <th>Details</th>
                      </tr>
                    </thead>
                    <tbody>
                      {playerData.games.map((game, idx) => (
                        <tr key={idx}>
                          <td>{formatDate(game.created_at)}</td>
                          <td>{game.position}</td>
                          <td>{game.team_side}</td>
                          <td className="score-cell">
                            {game.team_score} - {game.opponent_score}
                          </td>
                          <td>{game.opponent_team}</td>
                          <td>{game.stats.pts}</td>
                          <td>{game.stats.reb}</td>
                          <td>{game.stats.ast}</td>
                          <td>{game.stats.stl}</td>
                          <td>{game.stats.blk}</td>
                          <td>{game.grade || '-'}</td>
                          <td>
                            <Link to={`/games/${game.game_id}`}>View</Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}

            {playerData.games && playerData.games.length === 0 && (
              <EmptyState 
                title="No games found"
                message="This player hasn't played any games yet."
              />
            )}
          </>
        )}
      </div>
    </PageLayout>
  )
}

export default PlayerStatsPage

