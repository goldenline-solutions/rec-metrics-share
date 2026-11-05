import { useCallback, useEffect, useMemo, useState } from 'react'
import * as league from '../../utils/leagueApi'

// The free-agent pool. GMs sign for their own team, releasing someone in the
// same step when the roster is full; commissioners pick the team. The server
// enforces the roster size and the weekly lock either way.

const POSITIONS = ['All', 'PG', 'SG', 'SF', 'PF', 'C']

export default function FreeAgentsTab({ teams, myTeam, isCommish, locked, rosterSize, onSigned }) {
  const [players, setPlayers] = useState(null)
  const [error, setError] = useState(null)
  const [flash, setFlash] = useState(null)
  const [query, setQuery] = useState('')
  const [position, setPosition] = useState('All')
  const [teamId, setTeamId] = useState(myTeam?.id || '')
  const [roster, setRoster] = useState([])
  const [picking, setPicking] = useState(null) // player being signed onto a full roster
  const [release, setRelease] = useState('')
  const [busy, setBusy] = useState(false)

  const team = teams.find((t) => t.id === teamId) || null
  const canSign = !!team && (isCommish || (myTeam && team.id === myTeam.id && !locked))

  const load = useCallback(async () => {
    try {
      const data = await league.getFreeAgents()
      setPlayers(data.players || [])
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!teamId) { setRoster([]); return }
    league.getRoster(teamId).then((d) => setRoster(d.players || [])).catch(() => setRoster([]))
  }, [teamId])

  const full = roster.length >= rosterSize

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (players || []).filter((p) =>
      (position === 'All' || p.position === position || p.secondary_position === position) &&
      (!q || p.name.toLowerCase().includes(q)))
  }, [players, query, position])

  const sign = async (player, releaseName) => {
    setBusy(true)
    setError(null)
    try {
      const res = await league.signFreeAgent(player.name, { team: isCommish ? team.name : undefined, release: releaseName })
      setFlash(`${player.name} signed with the ${team.name}${res.released ? `; ${res.released.name} released` : ''}.`)
      setTimeout(() => setFlash(null), 4000)
      setPicking(null)
      setRelease('')
      await load()
      setRoster((await league.getRoster(team.id)).players || [])
      onSigned?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const start = (player) => {
    setError(null)
    // Commissioners may go over the limit; GMs must make room.
    if (full && !isCommish) { setPicking(player); setRelease('') } else sign(player)
  }

  if (!players && !error) return <p className="lg-muted">Loading free agents…</p>

  return (
    <div className="lg-fa">
      {flash && <div className="lg-flash">{flash}</div>}
      {error && <div className="lg-error">{error}</div>}
      {locked && !isCommish && <div className="lg-notice">{locked.replace('Trading', 'Signing')}</div>}

      <div className="lg-fabar">
        <input
          type="search"
          className="lg-fasearch"
          placeholder="Search players"
          aria-label="Search free agents"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="lg-seg" role="group" aria-label="Position">
          {POSITIONS.map((p) => (
            <button key={p} type="button" className={`lg-btn lg-btn-sm${position === p ? ' is-on' : ''}`} onClick={() => setPosition(p)}>{p}</button>
          ))}
        </div>
        {isCommish && (
          <select aria-label="Sign to team" value={teamId} onChange={(e) => { setTeamId(e.target.value); setPicking(null) }}>
            <option value="">Sign to…</option>
            {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        )}
        {team && (
          <span className={`lg-facount${full ? ' is-full' : ''}`}>
            {team.name}: {roster.length}/{rosterSize}{full ? ' · full' : ''}
          </span>
        )}
      </div>

      {picking && (
        <div className="lg-release">
          <p>
            The {team.name} roster is full. Release someone to sign <strong>{picking.name}</strong>.
          </p>
          <div className="lg-releaserow">
            <select aria-label="Player to release" value={release} onChange={(e) => setRelease(e.target.value)}>
              <option value="">Pick a player to release</option>
              {roster.map((p) => (
                <option key={p.id} value={p.name}>
                  {p.name} · {p.position || '—'}{p.ovr ? ` · ${p.ovr}` : ''}{p.is_untouchable ? ' · untouchable' : ''}
                </option>
              ))}
            </select>
            <button type="button" className="lg-btn lg-btn-go" disabled={!release || busy} onClick={() => sign(picking, release)}>
              {busy ? 'Signing…' : 'Release & sign'}
            </button>
            <button type="button" className="lg-btn" disabled={busy} onClick={() => setPicking(null)}>Cancel</button>
          </div>
        </div>
      )}

      <p className="lg-muted lg-fasummary">
        {shown.length} of {players.length} free agents
      </p>

      {shown.length === 0 ? (
        <div className="lg-empty"><p>No free agents match.</p></div>
      ) : (
        <div className="lg-tablewrap">
          <table className="lg-table lg-fatable">
            <thead>
              <tr>
                <th>Player</th>
                <th>Pos</th>
                <th className="num">OVR</th>
                <th className="num lg-wide">Age</th>
                {canSign && <th aria-label="Sign" />}
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <tr key={p.id} className={picking?.id === p.id ? 'is-picking' : ''}>
                  <td>
                    <span className="lg-teamname">{p.name}</span>
                    {p.is_rookie && <span className="lg-cpu">R</span>}
                  </td>
                  <td className="lg-muted">{p.position || '—'}{p.secondary_position ? ` / ${p.secondary_position}` : ''}</td>
                  <td className="num">{p.ovr ?? '—'}</td>
                  <td className="num lg-wide lg-muted">{p.age ?? '—'}</td>
                  {canSign && (
                    <td className="num">
                      <button type="button" className="lg-btn lg-btn-sm" disabled={busy} onClick={() => start(p)}>Sign</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
