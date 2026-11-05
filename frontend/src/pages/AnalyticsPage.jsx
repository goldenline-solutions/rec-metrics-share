import { useState, useEffect } from 'react'
import { NavLink, Link } from 'react-router-dom'
import { getRecImpactRating } from '../utils/api'
import { useVerifiedClaim } from '../hooks/useVerifiedClaim'
import './AnalyticsPage.css'

function AnalyticsPage() {
  const { verifiedClaim } = useVerifiedClaim()
  const [rirData, setRirData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedPlayer, setSelectedPlayer] = useState(null)
  const [minGames, setMinGames] = useState(5)
  const [sortBy, setSortBy] = useState('rir')
  const [positionFilter, setPositionFilter] = useState('all')

  useEffect(() => {
    loadRIR()
  }, [minGames])

  const loadRIR = async () => {
    setLoading(true)
    setError(null)
    
    try {
      const data = await getRecImpactRating(minGames)
      setRirData(data)
    } catch (err) {
      setError(err.message || 'Failed to load Rec Impact Rating')
    } finally {
      setLoading(false)
    }
  }

  const handlePlayerClick = (player) => {
    if (selectedPlayer && selectedPlayer.player_id === player.player_id) {
      setSelectedPlayer(null)
    } else {
      setSelectedPlayer(player)
    }
  }

  const getSortedRIR = () => {
    if (!rirData || !rirData.rir_leaderboard) return []
    
    // Filter by position first
    let filtered = [...rirData.rir_leaderboard]
    if (positionFilter !== 'all') {
      filtered = filtered.filter(player => player.primary_position === positionFilter)
    }
    
    // Then sort
    const sorted = [...filtered]
    
    switch(sortBy) {
      case 'rir':
        sorted.sort((a, b) => b.rir - a.rir)
        break
      case 'base_rir':
        sorted.sort((a, b) => b.base_rir - a.base_rir)
        break
      case 'pts_component':
        sorted.sort((a, b) => b.components.pts_component - a.components.pts_component)
        break
      case 'ast_component':
        sorted.sort((a, b) => b.components.ast_component - a.components.ast_component)
        break
      case 'defensive_component':
        sorted.sort((a, b) => b.components.defensive_component - a.components.defensive_component)
        break
      case 'reb_component':
        sorted.sort((a, b) => b.components.reb_component - a.components.reb_component)
        break
      case 'tov_penalty':
        // Lower is better for turnovers, so sort ascending
        sorted.sort((a, b) => a.components.tov_penalty - b.components.tov_penalty)
        break
      case 'usage_adjustment':
        sorted.sort((a, b) => b.usage_adjustment - a.usage_adjustment)
        break
      case 'efficiency_weight':
        sorted.sort((a, b) => b.efficiency_weight - a.efficiency_weight)
        break
      case 'stability_index':
        sorted.sort((a, b) => b.stability_index - a.stability_index)
        break
      default:
        break
    }
    
    // Update ranks based on new sort order
    sorted.forEach((player, idx) => {
      player.rank = idx + 1
    })
    
    return sorted
  }

  return (
    <div className="container">
      <div className="page-header">
        <h1>Rec Impact Rating (RIR)</h1>
        <nav>
          <NavLink to="/" end>Upload</NavLink>
          <NavLink to="/games">Games List</NavLink>
          <NavLink to="/stats">Stats</NavLink>
          <NavLink to="/leaderboard">Leaderboard</NavLink>
          {verifiedClaim && (
            <NavLink to={`/players/${encodeURIComponent(verifiedClaim.display_name)}`}>
              My Profile
            </NavLink>
          )}
          {import.meta.env.VITE_ENABLE_ANALYTICS === 'true' && (
            <NavLink to="/analytics">Analytics</NavLink>
          )}
        </nav>
      </div>

      <div className="analytics-content">
        <div className="rir-intro card">
          <h2>Rec Impact Rating (RIR) Explained</h2>
          <div className="rir-formula">
            <p><strong>RIR =</strong></p>
            <p>(PTS × efficiency_weight) + (AST × 1.25) + ((STL + BLK) × 1.5) + (REB × position_modifier) - (TO × 1.75)</p>
            <p>× Usage Adjustment</p>
          </div>
          
          <div className="rir-metrics-explanation">
            <h3>RIR Components</h3>
            <div className="metric-explanation-grid">
              <div className="metric-explanation-item">
                <div className="metric-title">Points Component</div>
                <div className="metric-desc">
                  Points multiplied by efficiency weight. Higher shooting percentages (FG%, 3PT%, FT%) increase the efficiency weight, 
                  meaning efficient scorers get more credit for their points. <strong>Higher is better.</strong>
                </div>
              </div>
              
              <div className="metric-explanation-item">
                <div className="metric-title">Assists Component (×1.25)</div>
                <div className="metric-desc">
                  Assists are weighted 1.25x because playmaking creates opportunities for teammates. 
                  Players who facilitate offense and create open shots are valuable. <strong>Higher is better.</strong>
                </div>
              </div>
              
              <div className="metric-explanation-item">
                <div className="metric-title">Defensive Component (×1.5)</div>
                <div className="metric-desc">
                  Steals and blocks combined, weighted 1.5x. These are high-impact plays that create turnovers and prevent scoring. 
                  Shows defensive activity and disruption. <strong>Higher is better.</strong>
                </div>
              </div>
              
              <div className="metric-explanation-item">
                <div className="metric-title">Rebounds Component</div>
                <div className="metric-desc">
                  Rebounds multiplied by position modifier (PG: 0.8, SG: 0.9, SF: 1.0, PF: 1.2, C: 1.3). 
                  Bigs get more credit since rebounding is their primary role. <strong>Higher is better.</strong>
                </div>
              </div>
              
              <div className="metric-explanation-item">
                <div className="metric-title">Turnover Penalty (×1.75)</div>
                <div className="metric-desc">
                  Turnovers are heavily penalized (1.75x) because they give the ball away and stop offensive possessions. 
                  Ball security is crucial for team success. <strong>Lower is better.</strong>
                </div>
              </div>
              
              <div className="metric-explanation-item">
                <div className="metric-title">Usage Adjustment</div>
                <div className="metric-desc">
                  Multiplier (0.7-1.3x) based on player's contribution to team scoring. High-usage players who carry more 
                  offensive load get a boost, while low-usage role players get a slight reduction. <strong>Higher is better.</strong>
                </div>
              </div>
            </div>
            
            <h3>Stability Index</h3>
            <div className="stability-explanation">
              <div className="metric-explanation-item">
                <div className="metric-title">Stability Index Formula</div>
                <div className="metric-desc">
                  <strong>(AST/(AST+TO)) × (FGM/FGA) × Team Assist Share</strong><br/><br/>
                  Measures how reliable and efficient a player is. Combines three factors:
                  <ul>
                    <li><strong>AST/(AST+TO):</strong> Assist-to-turnover ratio. Higher means better ball security and playmaking.</li>
                    <li><strong>FGM/FGA:</strong> Field goal percentage. Higher means more efficient shooting.</li>
                    <li><strong>Team Assist Share:</strong> Player's assists divided by team assists. Higher means more involved in team playmaking.</li>
                  </ul>
                  Players with high Stability Index are reliable, efficient, and contribute to team success. <strong>Higher is better.</strong>
                </div>
              </div>
            </div>
          </div>
        </div>

        {error && (
          <div className="error-message card">
            <strong>Error:</strong> {error}
            <button onClick={loadRIR} style={{ marginTop: '10px' }}>
              Retry
            </button>
          </div>
        )}

        <div className="analytics-controls card">
          <div className="control-group">
            <label htmlFor="sort-select">Sort by:</label>
            <select
              id="sort-select"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="sort-select"
              disabled={loading}
            >
              <option value="rir">Rec Impact Rating (RIR)</option>
              <option value="base_rir">Base RIR</option>
              <option value="pts_component">Points Component</option>
              <option value="ast_component">Assists Component</option>
              <option value="defensive_component">Defensive Component</option>
              <option value="reb_component">Rebounds Component</option>
              <option value="tov_penalty">Turnover Penalty (Lower Better)</option>
              <option value="usage_adjustment">Usage Adjustment</option>
              <option value="efficiency_weight">Efficiency Weight</option>
              <option value="stability_index">Stability Index</option>
            </select>
          </div>
          
          <div className="control-group">
            <label htmlFor="position-filter">Position:</label>
            <select
              id="position-filter"
              value={positionFilter}
              onChange={(e) => setPositionFilter(e.target.value)}
              className="position-select"
              disabled={loading}
            >
              <option value="all">All Positions</option>
              <option value="PG">Point Guard (PG)</option>
              <option value="SG">Shooting Guard (SG)</option>
              <option value="SF">Small Forward (SF)</option>
              <option value="PF">Power Forward (PF)</option>
              <option value="C">Center (C)</option>
            </select>
          </div>
          
          <div className="control-group">
            <label htmlFor="min-games">Minimum Games:</label>
            <input
              id="min-games"
              type="number"
              min="1"
              value={minGames}
              onChange={(e) => setMinGames(parseInt(e.target.value) || 5)}
              className="min-games-input"
              disabled={loading}
            />
          </div>
        </div>

        {loading && (
          <div className="loading card">
            Loading Rec Impact Rating stats...
          </div>
        )}

        {!loading && rirData && rirData.rir_leaderboard && rirData.rir_leaderboard.length > 0 && (
          <div className="rir-leaderboard">
            {getSortedRIR().map((player) => {
              const isExpanded = selectedPlayer && selectedPlayer.player_id === player.player_id
              
              return (
                <div key={player.player_id} className="rir-player-card card">
                  <div 
                    className="rir-player-header"
                    onClick={() => handlePlayerClick(player)}
                  >
                    <div className="rir-rank">
                      <span className={`rank-badge rank-${player.rank}`}>
                        {player.rank}
                      </span>
                    </div>
                    <div className="rir-player-info">
                      <h3>
                        <Link to={`/stats?q=${encodeURIComponent(player.gamertag)}`}>
                          {player.gamertag}
                        </Link>
                        <span className="position-tag">{player.primary_position}</span>
                      </h3>
                      <div className="rir-summary">
                        <div className="rir-main-score">
                          <span className="rir-label">RIR:</span>
                          <span className="rir-value">{player.rir.toFixed(2)}</span>
                        </div>
                        <div className="rir-secondary">
                          <span>{player.games_played} games</span>
                          <span>•</span>
                          <span>Usage: {player.usage_adjustment.toFixed(2)}x</span>
                        </div>
                      </div>
                    </div>
                    <div className="expand-icon">
                      {isExpanded ? '▼' : '▶'}
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="rir-details">
                      <div className="rir-breakdown">
                        <h4>RIR Breakdown</h4>
                        <div className="breakdown-grid">
                          <div className="breakdown-item positive">
                            <div className="breakdown-label">Points Component</div>
                            <div className="breakdown-value">
                              +{player.components.pts_component.toFixed(2)}
                            </div>
                            <div className="breakdown-detail">
                              {player.averages.pts.toFixed(1)} PTS × {player.efficiency_weight.toFixed(3)} efficiency
                            </div>
                          </div>
                          
                          <div className="breakdown-item positive">
                            <div className="breakdown-label">Assists Component</div>
                            <div className="breakdown-value">
                              +{player.components.ast_component.toFixed(2)}
                            </div>
                            <div className="breakdown-detail">
                              {player.averages.ast.toFixed(1)} AST × 1.25
                            </div>
                          </div>
                          
                          <div className="breakdown-item positive">
                            <div className="breakdown-label">Defensive Component</div>
                            <div className="breakdown-value">
                              +{player.components.defensive_component.toFixed(2)}
                            </div>
                            <div className="breakdown-detail">
                              ({player.averages.stl.toFixed(1)} STL + {player.averages.blk.toFixed(1)} BLK) × 1.5
                            </div>
                          </div>
                          
                          <div className="breakdown-item positive">
                            <div className="breakdown-label">Rebounds Component</div>
                            <div className="breakdown-value">
                              +{player.components.reb_component.toFixed(2)}
                            </div>
                            <div className="breakdown-detail">
                              {player.averages.reb.toFixed(1)} REB × {player.position_modifier} ({player.primary_position})
                            </div>
                          </div>
                          
                          <div className="breakdown-item negative">
                            <div className="breakdown-label">Turnover Penalty</div>
                            <div className="breakdown-value">
                              -{player.components.tov_penalty.toFixed(2)}
                            </div>
                            <div className="breakdown-detail">
                              {player.averages.tov.toFixed(1)} TO × 1.75
                            </div>
                          </div>
                        </div>
                        
                        <div className="rir-calculation">
                          <div className="calculation-step">
                            <strong>Base RIR:</strong> {player.base_rir.toFixed(2)}
                          </div>
                          <div className="calculation-step">
                            <strong>Usage Adjustment:</strong> × {player.usage_adjustment.toFixed(3)}
                          </div>
                          <div className="calculation-final">
                            <strong>Final RIR:</strong> {player.rir.toFixed(2)}
                          </div>
                        </div>
                      </div>

                      <div className="rir-stats">
                        <h4>Shooting Efficiency</h4>
                        <div className="shooting-stats">
                          <div className="shooting-stat">
                            <span className="shooting-label">FG%:</span>
                            <span className="shooting-value">{player.shooting.fg_pct}%</span>
                          </div>
                          <div className="shooting-stat">
                            <span className="shooting-label">3PT%:</span>
                            <span className="shooting-value">{player.shooting.tp_pct}%</span>
                          </div>
                          <div className="shooting-stat">
                            <span className="shooting-label">FT%:</span>
                            <span className="shooting-value">{player.shooting.ft_pct}%</span>
                          </div>
                          <div className="shooting-stat">
                            <span className="shooting-label">Efficiency Weight:</span>
                            <span className="shooting-value">{player.efficiency_weight.toFixed(3)}</span>
                          </div>
                        </div>
                      </div>

                      {player.stability_index !== undefined && (
                        <div className="rir-stats">
                          <h4>Stability Index</h4>
                          <div className="stability-breakdown">
                            <div className="stability-main">
                              <div className="stability-label">Stability Index</div>
                              <div className="stability-value">{player.stability_index.toFixed(4)}</div>
                            </div>
                            <div className="stability-formula">
                              <div className="formula-step">
                                AST/(AST+TO): <strong>{player.stability_components.ast_to_ratio.toFixed(3)}</strong>
                              </div>
                              <div className="formula-step">
                                × FGM/FGA: <strong>{player.stability_components.fg_ratio.toFixed(3)}</strong>
                              </div>
                              <div className="formula-step">
                                × Team Assist Share: <strong>{player.stability_components.team_assist_share.toFixed(3)}</strong>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {!loading && rirData && rirData.rir_leaderboard && rirData.rir_leaderboard.length === 0 && (
          <div className="card">
            <p>No players found matching the criteria.</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default AnalyticsPage
