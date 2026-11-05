import { useEffect, useState } from 'react'
import * as league from '../../utils/leagueApi'

// Standings and award races. Both are computed server-side from saved box
// scores on every load, so an edited game fixes them immediately.

const AWARDS = [
  ['mvp', 'MVP'],
  ['dpoy', 'Defensive Player'],
  ['roy', 'Rookie of the Year'],
  ['smoy', 'Sixth Man'],
]

const pct = (v) => v.toFixed(3).replace(/^0/, '')

export default function StandingsTab({ myTeamId }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    league.getStandings().then(setData).catch((err) => setError(err.message))
  }, [])

  if (error) return <div className="lg-error">{error}</div>
  if (!data) return <p className="lg-muted">Loading standings…</p>

  return (
    <div className="lg-standings">
      {data.games_played === 0 && (
        <div className="lg-empty">
          <p>No games saved yet.</p>
          <p className="lg-muted">Standings fill in once the first sim’s box scores are uploaded on the Scores tab.</p>
        </div>
      )}

      <div className="lg-confs">
        {data.standings.map((conf) => (
          <section key={conf.conference}>
            <h2 className="lg-subhead">{conf.conference}</h2>
            <div className="lg-tablewrap">
              <table className="lg-table lg-standtable">
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th>Team</th>
                    <th className="num">W</th>
                    <th className="num">L</th>
                    <th className="num">PCT</th>
                    <th className="num">GB</th>
                    <th className="num lg-wide">PPG</th>
                    <th className="num lg-wide">OPP</th>
                    <th className="num">DIFF</th>
                    <th className="num lg-wide">L10</th>
                    <th className="num">STRK</th>
                  </tr>
                </thead>
                <tbody>
                  {conf.teams.map((r) => (
                    <tr key={r.team.id} className={r.team.id === myTeamId ? 'is-mine' : ''}>
                      <td className="num lg-muted">{r.rank}</td>
                      <td>
                        <span className="lg-teamname">{r.team.name}</span>
                        {r.team.is_cpu && <span className="lg-cpu">CPU</span>}
                      </td>
                      <td className="num">{r.w}</td>
                      <td className="num">{r.l}</td>
                      <td className="num">{pct(r.pct)}</td>
                      <td className="num lg-muted">{r.gb}</td>
                      <td className="num lg-wide">{r.ppg ?? '—'}</td>
                      <td className="num lg-wide">{r.oppg ?? '—'}</td>
                      <td className={`num ${r.diff > 0 ? 'lg-up' : r.diff < 0 ? 'lg-down' : ''}`}>
                        {r.diff == null ? '—' : r.diff > 0 ? `+${r.diff}` : r.diff}
                      </td>
                      <td className="num lg-wide">{r.gp ? r.last10 : '—'}</td>
                      <td className="num">{r.streak || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>

      <section>
        <h2 className="lg-subhead">Award races</h2>
        <div className="lg-awards">
          {AWARDS.map(([key, label]) => {
            const race = data.awards[key]
            return (
              <article key={key} className="lg-award">
                <h3>{label}</h3>
                {race.leaders.length === 0 ? (
                  <p className="lg-muted">
                    {key === 'roy' ? 'Nobody qualifies yet. Rookies have to be marked on the roster first.' : 'Nobody qualifies yet.'}
                  </p>
                ) : (
                  <ol>
                    {race.leaders.map((e) => (
                      <li key={e.player_id || e.name}>
                        <span className="lg-awardname">{e.name}</span>
                        <span className="lg-muted"> {e.team?.abbrev}</span>
                        <div className="lg-awardline">{e.line}</div>
                      </li>
                    ))}
                  </ol>
                )}
                <p className="lg-awardhow">{race.how} Needs half the team’s games.</p>
              </article>
            )
          })}
        </div>
      </section>
    </div>
  )
}
