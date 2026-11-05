import './BoxScoreSummary.css'

/**
 * BoxScoreSummary component - displays a compact box score summary
 * 
 * Props:
 * - payload: object - the game payload from the backend
 */
function BoxScoreSummary({ payload }) {
  if (!payload) return null

  const { game, teams, players } = payload

  // Get team data
  const awayTeam = teams.find(t => t.side === 'AWAY')
  const homeTeam = teams.find(t => t.side === 'HOME')

  // Get quarter scores
  const awayQuarters = game.quarters?.away || []
  const homeQuarters = game.quarters?.home || []

  // Separate players by team
  const awayPlayers = players.filter(p => p.side === 'AWAY').sort((a, b) => a.row_index - b.row_index)
  const homePlayers = players.filter(p => p.side === 'HOME').sort((a, b) => a.row_index - b.row_index)

  return (
    <div className="box-score-summary">
      <div className="score-header">
        <div className="team-score">
          <div className="team-name">Away</div>
          <div className="final-score">{game.away_score}</div>
        </div>
        <div className="vs">vs</div>
        <div className="team-score">
          <div className="team-name">Home</div>
          <div className="final-score">{game.home_score}</div>
        </div>
      </div>

      <div className="quarters-section">
        <h3>Quarter Scores</h3>
        <div className="quarters-grid">
          <div className="quarter-row">
            <div className="quarter-label">Q1</div>
            <div className="quarter-score">{awayQuarters[0] ?? '-'}</div>
            <div className="quarter-score">{homeQuarters[0] ?? '-'}</div>
          </div>
          <div className="quarter-row">
            <div className="quarter-label">Q2</div>
            <div className="quarter-score">{awayQuarters[1] ?? '-'}</div>
            <div className="quarter-score">{homeQuarters[1] ?? '-'}</div>
          </div>
          <div className="quarter-row">
            <div className="quarter-label">Q3</div>
            <div className="quarter-score">{awayQuarters[2] ?? '-'}</div>
            <div className="quarter-score">{homeQuarters[2] ?? '-'}</div>
          </div>
          <div className="quarter-row">
            <div className="quarter-label">Q4</div>
            <div className="quarter-score">{awayQuarters[3] ?? '-'}</div>
            <div className="quarter-score">{homeQuarters[3] ?? '-'}</div>
          </div>
        </div>
      </div>

      <div className="team-totals-section">
        <h3>Team Totals</h3>
        <div className="team-totals-grid">
          {awayTeam && (
            <div className="team-totals-card">
              <div className="team-totals-header">Away Team</div>
              <div className="team-totals-grade">Grade: {awayTeam.grade || 'N/A'}</div>
              <div className="team-totals-stats">
                <div>PTS: {awayTeam.totals.pts}</div>
                <div>REB: {awayTeam.totals.reb}</div>
                <div>AST: {awayTeam.totals.ast}</div>
                <div>STL: {awayTeam.totals.stl}</div>
                <div>BLK: {awayTeam.totals.blk}</div>
                <div>TOV: {awayTeam.totals.tov}</div>
              </div>
            </div>
          )}
          {homeTeam && (
            <div className="team-totals-card">
              <div className="team-totals-header">Home Team</div>
              <div className="team-totals-grade">Grade: {homeTeam.grade || 'N/A'}</div>
              <div className="team-totals-stats">
                <div>PTS: {homeTeam.totals.pts}</div>
                <div>REB: {homeTeam.totals.reb}</div>
                <div>AST: {homeTeam.totals.ast}</div>
                <div>STL: {homeTeam.totals.stl}</div>
                <div>BLK: {homeTeam.totals.blk}</div>
                <div>TOV: {homeTeam.totals.tov}</div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="players-section">
        <h3>Players</h3>
        <div className="players-grid">
          <div className="players-column">
            <div className="players-header">Away Team</div>
            {awayPlayers.map((player, idx) => (
              <div key={idx} className="player-row">
                <div className="player-info">
                  <span className="player-position">{player.assigned_position || 'N/A'}</span>
                  <span className="player-name">{player.gamertag}</span>
                  {player.grade && <span className="player-grade">({player.grade})</span>}
                </div>
                <div className="player-stats">
                  {player.stats.pts} PTS, {player.stats.reb} REB, {player.stats.ast} AST
                </div>
              </div>
            ))}
          </div>
          <div className="players-column">
            <div className="players-header">Home Team</div>
            {homePlayers.map((player, idx) => (
              <div key={idx} className="player-row">
                <div className="player-info">
                  <span className="player-position">{player.assigned_position || 'N/A'}</span>
                  <span className="player-name">{player.gamertag}</span>
                  {player.grade && <span className="player-grade">({player.grade})</span>}
                </div>
                <div className="player-stats">
                  {player.stats.pts} PTS, {player.stats.reb} REB, {player.stats.ast} AST
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default BoxScoreSummary

