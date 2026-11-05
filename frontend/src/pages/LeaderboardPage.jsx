import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getLeaderboard } from '../utils/api'
import PageLayout from '../components/PageLayout'
import GameVersionSwitch from '../components/GameVersionSwitch'
import { useGameVersion } from '../contexts/GameVersionContext'
import Card from '../components/ui/Card'
import SectionHeader from '../components/ui/SectionHeader'
import Badge from '../components/ui/Badge'
import EmptyState from '../components/ui/EmptyState'
import Seo from '../components/Seo'
import './LeaderboardPage.css'

function LeaderboardPage() {
  const { gameVersion } = useGameVersion()
  const [selectedStat, setSelectedStat] = useState('pts')
  const [selectedPosition, setSelectedPosition] = useState('ALL')
  const [selectedPlatform, setSelectedPlatform] = useState('ALL')
  const [leaderboard, setLeaderboard] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [minGames, setMinGames] = useState(5)

  const positionOptions = [
    { value: 'ALL', label: 'All Positions' },
    { value: 'PG', label: 'Point Guard (PG)' },
    { value: 'SG', label: 'Shooting Guard (SG)' },
    { value: 'SF', label: 'Small Forward (SF)' },
    { value: 'PF', label: 'Power Forward (PF)' },
    { value: 'C', label: 'Center (C)' }
  ]

  const platformOptions = [
    { value: 'ALL', label: 'All Platforms' },
    { value: 'PC', label: 'PC' },
    { value: 'Console', label: 'Console' }
  ]

  const statOptions = [
    { value: 'pts', label: 'Points', format: (val) => val.toLocaleString() },
    { value: 'avg_pts', label: 'Points Per Game', format: (val) => val.toFixed(1) },
    { value: 'reb', label: 'Rebounds', format: (val) => val.toLocaleString() },
    { value: 'avg_reb', label: 'Rebounds Per Game', format: (val) => val.toFixed(1) },
    { value: 'ast', label: 'Assists', format: (val) => val.toLocaleString() },
    { value: 'avg_ast', label: 'Assists Per Game', format: (val) => val.toFixed(1) },
    { value: 'stl', label: 'Steals', format: (val) => val.toLocaleString() },
    { value: 'blk', label: 'Blocks', format: (val) => val.toLocaleString() },
    { value: 'fg_pct', label: 'Field Goal %', format: (val) => `${val.toFixed(1)}%` },
    { value: 'tp_pct', label: '3-Point %', format: (val) => `${val.toFixed(1)}%` },
    { value: 'ft_pct', label: 'Free Throw %', format: (val) => `${val.toFixed(1)}%` },
    { value: 'games', label: 'Games Played', format: (val) => val.toLocaleString() },
    { value: 'avg_tpm', label: '3PTM Per Game', format: (val) => val.toFixed(1) },
    { value: 'avg_tpa', label: '3PTA Per Game', format: (val) => val.toFixed(1) },
    { value: 'winrate', label: 'Win Rate', format: (val) => `${val.toFixed(1)}%` },
  ]

  const loadLeaderboard = useCallback(async () => {
    setLoading(true)
    setError(null)
    setLeaderboard(null)
    try {
      const data = await getLeaderboard(selectedStat, 50, minGames, selectedPosition, selectedPlatform, gameVersion)
      setLeaderboard(data)
    } catch (err) {
      setError(err.message || 'Failed to load leaderboard')
    } finally {
      setLoading(false)
    }
  }, [selectedStat, minGames, selectedPosition, selectedPlatform, gameVersion])

  useEffect(() => {
    loadLeaderboard()
  }, [loadLeaderboard])

  const getStatValue = (player, stat) => {
    switch(stat) {
      case 'pts': return player.pts
      case 'avg_pts': return player.avg_pts
      case 'reb': return player.reb
      case 'avg_reb': return player.avg_reb
      case 'ast': return player.ast
      case 'avg_ast': return player.avg_ast
      case 'stl': return player.stl
      case 'blk': return player.blk
      case 'fg_pct': return player.fg_pct
      case 'tp_pct': return player.tp_pct
      case 'ft_pct': return player.ft_pct
      case 'games': return player.games_played
      case 'avg_tpm': return player.avg_tpm
      case 'avg_tpa': return player.avg_tpa
      case 'winrate': return player.winrate
      default: return 0
    }
  }

  const getSelectedStatOption = () => {
    return statOptions.find(opt => opt.value === selectedStat) || statOptions[0]
  }

  const statOption = getSelectedStatOption()

  return (
    <PageLayout title="Leaderboards">
      <Seo
        title="NBA 2K26 REC Leaderboards | RecMetrics"
        description="NBA 2K26 REC leaderboards — top players by points, rebounds, assists and more, filterable by position and platform."
        path="/leaderboard"
      />
      <div className="leaderboard-content">
        <Card className="leaderboard-controls">
          <GameVersionSwitch className="control-group" />

          <div className="control-group">
            <label htmlFor="stat-select">Rank by:</label>
            <select
              id="stat-select"
              value={selectedStat}
              onChange={(e) => setSelectedStat(e.target.value)}
              className="stat-select"
            >
              {statOptions.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          
          <div className="control-group">
            <label htmlFor="position-select">Position:</label>
            <select
              id="position-select"
              value={selectedPosition}
              onChange={(e) => setSelectedPosition(e.target.value)}
              className="position-select"
            >
              {positionOptions.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          
          <div className="control-group">
            <label htmlFor="platform-select">Platform:</label>
            <select
              id="platform-select"
              value={selectedPlatform}
              onChange={(e) => setSelectedPlatform(e.target.value)}
              className="platform-select"
            >
              {platformOptions.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          
          <div className="control-group">
            <label htmlFor="min-games">Minimum Games:</label>
            <input
              id="min-games"
              type="number"
              min="1"
              value={minGames}
              onChange={(e) => setMinGames(parseInt(e.target.value) || 1)}
              className="min-games-input"
            />
          </div>
        </Card>

        {error && (
          <Card className="leaderboard-error-card">
            <div className="error-message">
              <strong>Error:</strong> {error}
              <button onClick={loadLeaderboard} style={{ marginTop: 'var(--spacing-sm)' }}>
                Retry
              </button>
            </div>
          </Card>
        )}

        {loading && !leaderboard && (
          <Card>
            <SectionHeader title={statOption.label + ' Leaderboard'} />
            <div className="leaderboard-skeleton">
              {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
                <div key={i} className="leaderboard-skeleton-row" />
              ))}
            </div>
          </Card>
        )}

        {leaderboard && leaderboard.leaderboard && !loading && !error && (
          <Card>
            <SectionHeader 
              title={
                <>
                  {gameVersion} {statOption.label} Leaderboard
                  {selectedPosition !== 'ALL' && (
                    <span className="leaderboard-subtitle">
                      {' '}- {positionOptions.find(p => p.value === selectedPosition)?.label.replace(/ \(.*\)/, '')}
                    </span>
                  )}
                  {selectedPlatform !== 'ALL' && (
                    <span className="leaderboard-subtitle">
                      {' '}- {platformOptions.find(p => p.value === selectedPlatform)?.label}
                    </span>
                  )}
                </>
              }
            />
            <div className="rtable-wrap">
            <table className="leaderboard-table rtable">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Player</th>
                  <th>{statOption.label}</th>
                  <th>Games</th>
                  <th>PTS</th>
                  <th>REB</th>
                  <th>AST</th>
                  <th>FG%</th>
                  <th>3PT%</th>
                  {/* <th>3PTM/G</th> */}
                  {/* <th>3PTA/G</th> */}
                </tr>
              </thead>
              <tbody>
                {leaderboard.leaderboard.map((player) => {
                  const statValue = getStatValue(player, selectedStat)
                  const rankVariant = player.rank <= 3 ? 'positive' : 'default'
                  return (
                    <tr key={player.player_id}>
                      <td className="rank-cell" data-label="Rank">
                        <Badge variant={rankVariant}>
                          {player.rank}
                        </Badge>
                      </td>
                      <td className="player-cell rtable-primary" data-label="Player">
                        <Link to={`/players/${encodeURIComponent(player.gamertag)}`}>
                          {player.gamertag}
                        </Link>
                      </td>
                      <td className="stat-value-cell" data-label={statOption.label}>
                        <strong>{statOption.format(statValue)}</strong>
                      </td>
                      <td data-label="Games">{player.games_played}</td>
                      <td data-label="PTS">{player.pts.toLocaleString()}</td>
                      <td data-label="REB">{player.reb.toLocaleString()}</td>
                      <td data-label="AST">{player.ast.toLocaleString()}</td>
                      <td data-label="FG%">{player.fg_pct.toFixed(1)}%</td>
                      <td data-label="3PT%">{player.tp_pct.toFixed(1)}%</td>
                      {/* <td>{player.avg_tpm ? player.avg_tpm.toFixed(1) : '0.0'}</td> */}
                      {/* <td>{player.avg_tpa ? player.avg_tpa.toFixed(1) : '0.0'}</td> */}
                    </tr>
                  )
                })}
              </tbody>
            </table>
            </div>
          </Card>
        )}

        {leaderboard && leaderboard.leaderboard && leaderboard.leaderboard.length === 0 && !loading && (
          <EmptyState 
            title="No players found"
            message={`No ${gameVersion} players match the selected criteria. Try adjusting your filters, or switch titles above.`}
          />
        )}

      </div>
    </PageLayout>
  )
}

export default LeaderboardPage

