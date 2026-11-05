import { useEffect, useMemo, useState } from 'react'
import * as league from '../../utils/leagueApi'

// Player stats from saved box scores: per-game averages or season totals,
// sortable, filterable by team.

const COLUMNS = [
  ['gp', 'GP'], ['minutes', 'MIN'], ['pts', 'PTS'], ['reb', 'REB'], ['ast', 'AST'],
  ['stl', 'STL'], ['blk', 'BLK'], ['tov', 'TO'], ['fg_pct', 'FG%'], ['tp_pct', '3P%'],
  ['ft_pct', 'FT%'], ['game_score', 'GmSc'],
]
const PCTS = new Set(['fg_pct', 'tp_pct', 'ft_pct'])

function value(row, key, mode) {
  if (key === 'gp' || key === 'game_score' || PCTS.has(key)) return row[key]
  return mode === 'avg' ? row.per_game[key] : row.totals[key]
}

function show(v, key) {
  if (v == null) return '—'
  if (PCTS.has(key)) return (v * 100).toFixed(1)
  return v
}

export default function StatsTab({ teams, myTeamId }) {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)
  const [mode, setMode] = useState('avg')
  const [sort, setSort] = useState('pts')
  const [teamId, setTeamId] = useState('')

  useEffect(() => {
    league.getLeagueStats().then((d) => setRows(d.players || [])).catch((err) => setError(err.message))
  }, [])

  const shown = useMemo(() => {
    const list = (rows || []).filter((r) => !teamId || r.team?.id === teamId)
    return [...list].sort((a, b) => (value(b, sort, mode) ?? -1) - (value(a, sort, mode) ?? -1))
  }, [rows, teamId, sort, mode])

  if (error) return <div className="lg-error">{error}</div>
  if (!rows) return <p className="lg-muted">Loading stats…</p>

  return (
    <div className="lg-stats">
      <div className="lg-statbar">
        <div className="lg-seg" role="group" aria-label="Show">
          <button type="button" className={`lg-btn lg-btn-sm${mode === 'avg' ? ' is-on' : ''}`} onClick={() => setMode('avg')}>Per game</button>
          <button type="button" className={`lg-btn lg-btn-sm${mode === 'tot' ? ' is-on' : ''}`} onClick={() => setMode('tot')}>Totals</button>
        </div>
        <select aria-label="Team" value={teamId} onChange={(e) => setTeamId(e.target.value)}>
          <option value="">All teams</option>
          {myTeamId && <option value={myTeamId}>My team</option>}
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>

      {shown.length === 0 ? (
        <div className="lg-empty">
          <p>No stats yet.</p>
          <p className="lg-muted">They fill in from the box scores saved on the Scores tab.</p>
        </div>
      ) : (
        <div className="lg-tablewrap">
          <table className="lg-table lg-stattable">
            <thead>
              <tr>
                <th>Player</th>
                <th>Team</th>
                {COLUMNS.map(([k, l]) => (
                  <th key={k} className="num">
                    <button type="button" className={`lg-sort${sort === k ? ' is-on' : ''}`} onClick={() => setSort(k)}>{l}</button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.player_id || `${r.box_name}|${r.team?.id}`} className={r.team?.id === myTeamId ? 'is-mine' : ''}>
                  <td>
                    {r.name}
                    {!r.linked && <span className="lg-muted" title="2K name, not linked to a league player"> *</span>}
                    {r.is_rookie && <span className="lg-cpu">R</span>}
                  </td>
                  <td className="lg-muted">{r.team?.abbrev}</td>
                  {COLUMNS.map(([k]) => (
                    <td key={k} className={`num${sort === k ? ' is-sorted' : ''}`}>{show(value(r, k, mode), k)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="lg-muted lg-footnote">* 2K name that isn’t linked to a league player. GmSc is Game Score per game.</p>
    </div>
  )
}
