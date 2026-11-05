import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as league from '../../utils/leagueApi'

// Game results. Everyone sees the saved games; a commissioner can upload 2K
// box-score screenshots, fix anything misread, and save. Standings and stats
// are computed from what's saved here.

const STATS = [
  ['minutes', 'MIN'], ['pts', 'PTS'], ['reb', 'REB'], ['ast', 'AST'], ['stl', 'STL'],
  ['blk', 'BLK'], ['tov', 'TO'], ['fgm', 'FGM'], ['fga', 'FGA'], ['tpm', '3PM'],
  ['tpa', '3PA'], ['ftm', 'FTM'], ['fta', 'FTA'], ['oreb', 'OR'], ['fouls', 'PF'],
]
const SIDES = ['away', 'home']
// The IIS proxy gives up after ~120s, so screenshots go one per request.
const PARALLEL_READS = 3

const n = (v) => Number.parseInt(v, 10) || 0

// Mirrors check_game() in backend/mynba_games.py: problems worth a look that don't block saving.
function checkGame(game, teamsById) {
  const out = []
  for (const side of SIDES) {
    const s = game[side]
    const label = teamsById[s.team_id]?.name || s.read_as || side
    const quarters = s.quarters || []
    const sumQ = quarters.reduce((a, q) => a + n(q), 0)
    if (quarters.length && sumQ !== n(s.score)) out.push(`${label}: period scores add up to ${sumQ}, not ${n(s.score)}.`)
    if (!s.lines) {
      out.push(`${label}: no box score. The result still counts; their player stats won't.`)
      continue
    }
    const pts = s.lines.reduce((a, l) => a + n(l.pts), 0)
    if (pts !== n(s.score)) out.push(`${label}: player points add up to ${pts}, not ${n(s.score)}.`)
    const mins = s.lines.reduce((a, l) => a + n(l.minutes), 0)
    const expected = 240 + 25 * (Math.max(4, quarters.length) - 4)
    if (s.lines.length && Math.abs(mins - expected) > 2) out.push(`${label}: minutes add up to ${mins}, expected about ${expected}.`)
    for (const l of s.lines) {
      const made = 2 * n(l.fgm) + n(l.tpm) + n(l.ftm)
      if (made !== n(l.pts)) out.push(`${label}: ${l.player_name || 'a player'} has ${n(l.pts)} PTS but the shooting adds up to ${made}.`)
      if (!l.player_id) out.push(`${label}: ${l.player_name || 'a player'} isn't linked to a league player.`)
    }
  }
  if (game.away.team_id && game.away.team_id === game.home.team_id) out.push('Both sides are the same team.')
  return out
}

function draftKey(g) {
  const side = (s) => s.team_id || s.read_as
  return `${side(g.away)}|${side(g.home)}|${g.away.score}|${g.home.score}`
}

// One request per screenshot means one draft per screenshot; fold the two
// halves of a game back together.
function mergeDrafts(list, incoming) {
  const out = [...list]
  for (const g of incoming) {
    const i = out.findIndex((d) => !d.id && draftKey(d) === draftKey(g))
    if (i === -1) {
      out.push({ ...g, key: `${draftKey(g)}|${Math.random()}` })
      continue
    }
    const d = { ...out[i], files: [...out[i].files, ...g.files], notes: [...out[i].notes, ...g.notes] }
    for (const side of SIDES) {
      if (!d[side].lines && g[side].lines) d[side] = g[side]
      else if (d[side].lines && g[side].lines) d.notes = [...d.notes, `A second ${d[side].read_as} box score; kept the first.`]
    }
    out[i] = d
  }
  return out
}

function formatDate(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

export default function ScoresTab({ teams, isCommish, onSaved }) {
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [drafts, setDrafts] = useState([])
  const [reading, setReading] = useState(null) // {done, total}
  const [unread, setUnread] = useState([])
  const [openId, setOpenId] = useState(null)
  const [editing, setEditing] = useState(null)
  const fileInput = useRef(null)

  const teamsById = useMemo(() => Object.fromEntries(teams.map((t) => [t.id, t])), [teams])

  const load = useCallback(async () => {
    try {
      const data = await league.getGames()
      setGames(data.games || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const readFiles = async (fileList) => {
    const files = [...fileList].filter((f) => f.type.startsWith('image/'))
    if (!files.length) return
    setError(null)
    setReading({ done: 0, total: files.length })
    const queue = [...files]
    const worker = async () => {
      while (queue.length) {
        const file = queue.shift()
        try {
          const res = await league.readBoxScore(file)
          setDrafts((cur) => mergeDrafts(cur, res.games || []))
          if (res.unread?.length) setUnread((cur) => [...cur, ...res.unread])
        } catch (err) {
          setUnread((cur) => [...cur, { file: file.name, reason: err.message }])
        }
        setReading((r) => ({ ...r, done: r.done + 1 }))
      }
    }
    await Promise.all(Array.from({ length: Math.min(PARALLEL_READS, files.length) }, worker))
    setReading(null)
  }

  const afterSave = async (key) => {
    setDrafts((cur) => cur.filter((d) => d.key !== key))
    setEditing(null)
    await load()
    onSaved?.()
  }

  const remove = async (game) => {
    if (!window.confirm(`Delete ${game.away.team_name} ${game.away.score} – ${game.home.team_name} ${game.home.score}? Standings and stats update right away.`)) return
    try {
      await league.deleteGame(game.id)
      await load()
      onSaved?.()
    } catch (err) {
      setError(err.message)
    }
  }

  const byDate = useMemo(() => {
    const groups = new Map()
    for (const g of games) {
      if (!groups.has(g.played_on)) groups.set(g.played_on, [])
      groups.get(g.played_on).push(g)
    }
    return [...groups.entries()]
  }, [games])

  return (
    <div className="lg-scores">
      {error && <div className="lg-error">{error}</div>}

      {isCommish && (
        <section
          className="lg-upload"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); if (!reading) readFiles(e.dataTransfer.files) }}
        >
          <div>
            <h2 className="lg-subhead">Add box scores</h2>
            <p className="lg-muted">
              Drop the 2K box-score screenshots from the sim: one per team, any number of games at once.
              Nothing is saved until you check each game and press Save.
            </p>
          </div>
          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={(e) => { readFiles(e.target.files); e.target.value = '' }}
          />
          <button type="button" className="lg-btn lg-btn-go" disabled={!!reading} onClick={() => fileInput.current?.click()}>
            {reading ? `Reading ${reading.done}/${reading.total}…` : 'Choose screenshots'}
          </button>
          {reading && <p className="lg-muted lg-upload-note">About 40 seconds per screenshot, 3 at a time.</p>}
        </section>
      )}

      {unread.length > 0 && (
        <div className="lg-notice">
          {unread.map((u, i) => <div key={i}><strong>{u.file}</strong>: {u.reason}</div>)}
          <button type="button" className="lg-btn lg-btn-sm" onClick={() => setUnread([])}>Dismiss</button>
        </div>
      )}

      {drafts.map((d) => (
        <GameEditor
          key={d.key}
          initial={d}
          teams={teams}
          teamsById={teamsById}
          onSaved={() => afterSave(d.key)}
          onDiscard={() => setDrafts((cur) => cur.filter((x) => x.key !== d.key))}
        />
      ))}

      {editing && (
        <GameEditor
          key={editing.id}
          initial={editing}
          teams={teams}
          teamsById={teamsById}
          onSaved={() => afterSave(null)}
          onDiscard={() => setEditing(null)}
        />
      )}

      {loading ? (
        <p className="lg-muted">Loading games…</p>
      ) : games.length === 0 ? (
        <div className="lg-empty">
          <p>No games saved yet.</p>
          <p className="lg-muted">{isCommish ? 'Upload the first sim’s box scores above.' : 'Results show up here after the commissioner uploads the sim.'}</p>
        </div>
      ) : (
        byDate.map(([day, list]) => (
          <section key={day} className="lg-gameday">
            <h2 className="lg-subhead">{formatDate(day)}</h2>
            <ul className="lg-gamelist">
              {list.map((g) => {
                const awayWon = g.away.score > g.home.score
                const open = openId === g.id
                return (
                  <li key={g.id} className={`lg-game${open ? ' is-open' : ''}`}>
                    <button type="button" className="lg-gamerow" onClick={() => setOpenId(open ? null : g.id)} aria-expanded={open}>
                      <span className={`lg-gameteam${awayWon ? ' is-win' : ''}`}>{g.away.team_name}<b>{g.away.score}</b></span>
                      <span className="lg-at">at</span>
                      <span className={`lg-gameteam${!awayWon ? ' is-win' : ''}`}>{g.home.team_name}<b>{g.home.score}</b></span>
                      {isCommish && g.warnings.length > 0 && <span className="lg-gamewarn" title={g.warnings.join('\n')}>{g.warnings.length} to check</span>}
                    </button>
                    {open && (
                      <div className="lg-boxscore">
                        {SIDES.map((side) => <BoxTable key={side} side={g[side]} />)}
                        {isCommish && (
                          <div className="lg-gameactions">
                            <button type="button" className="lg-btn lg-btn-sm" onClick={() => setEditing({ ...g, key: g.id, files: [], notes: [] })}>Edit</button>
                            <button type="button" className="lg-btn lg-btn-sm lg-btn-stop" onClick={() => remove(g)}>Delete</button>
                          </div>
                        )}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}

function BoxTable({ side }) {
  const shown = STATS.filter(([k]) => !['fgm', 'fga', 'tpm', 'tpa', 'ftm', 'fta'].includes(k))
  return (
    <div className="lg-tablewrap">
      <h3 className="lg-boxhead">
        {side.team_name} <span className="lg-muted">{(side.quarters || []).join(' · ')}</span>
      </h3>
      {!side.lines ? (
        <p className="lg-muted">No box score saved for this team.</p>
      ) : (
        <table className="lg-table lg-boxtable">
          <thead>
            <tr>
              <th>Player</th>
              {shown.slice(0, 7).map(([k, l]) => <th key={k} className="num">{l}</th>)}
              <th className="num">FG</th><th className="num">3PT</th><th className="num">FT</th>
              {shown.slice(7).map(([k, l]) => <th key={k} className="num">{l}</th>)}
            </tr>
          </thead>
          <tbody>
            {side.lines.map((l, i) => (
              <tr key={i}>
                <td>{l.player_full_name || <span title="Not linked to a league player">{l.player_name}*</span>}</td>
                {shown.slice(0, 7).map(([k]) => <td key={k} className="num">{l[k]}</td>)}
                <td className="num">{l.fgm}-{l.fga}</td><td className="num">{l.tpm}-{l.tpa}</td><td className="num">{l.ftm}-{l.fta}</td>
                {shown.slice(7).map(([k]) => <td key={k} className="num">{l[k]}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

const blankLine = () => ({ player_name: '', player_id: null, ...Object.fromEntries(STATS.map(([k]) => [k, 0])) })

function GameEditor({ initial, teams, teamsById, onSaved, onDiscard }) {
  const [game, setGame] = useState(() => ({
    id: initial.id,
    played_on: initial.played_on,
    away: { ...initial.away, quarters: [...(initial.away.quarters || [])] },
    home: { ...initial.home, quarters: [...(initial.home.quarters || [])] },
  }))
  const [rosters, setRosters] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [duplicate, setDuplicate] = useState(false)

  useEffect(() => {
    for (const side of SIDES) {
      const id = game[side].team_id
      if (id && !rosters[id]) {
        league.getRoster(id)
          .then((d) => setRosters((cur) => ({ ...cur, [id]: d.players || [] })))
          .catch(() => setRosters((cur) => ({ ...cur, [id]: [] })))
      }
    }
  }, [game.away.team_id, game.home.team_id]) // eslint-disable-line react-hooks/exhaustive-deps

  const warnings = useMemo(() => checkGame(game, teamsById), [game, teamsById])

  const setSide = (side, patch) => setGame((g) => ({ ...g, [side]: { ...g[side], ...patch } }))
  const setLine = (side, i, patch) =>
    setGame((g) => ({ ...g, [side]: { ...g[side], lines: g[side].lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) } }))

  const save = async (allowDuplicate = false) => {
    setSaving(true)
    setError(null)
    try {
      const body = {
        id: game.id,
        played_on: game.played_on,
        ...Object.fromEntries(SIDES.map((side) => [side, {
          team_id: game[side].team_id,
          score: n(game[side].score),
          quarters: game[side].quarters.map(n),
          lines: (game[side].lines || []).map((l) => ({
            player_name: l.player_name,
            player_id: l.player_id || null,
            ...Object.fromEntries(STATS.map(([k]) => [k, n(l[k])])),
          })),
        }])),
      }
      await league.saveGame(body, { allowDuplicate })
      onSaved()
    } catch (err) {
      setError(err.message)
      setDuplicate(err.code === 'duplicate_game')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="lg-editor">
      <header className="lg-editorhead">
        <h2>{game.id ? 'Edit game' : 'Check this game'}</h2>
        {initial.files?.length > 0 && <span className="lg-muted">{initial.files.join(', ')}</span>}
      </header>

      <label className="lg-field lg-datefield">
        <span>Sim date</span>
        <input type="date" value={game.played_on} onChange={(e) => setGame((g) => ({ ...g, played_on: e.target.value }))} />
      </label>

      {SIDES.map((side) => {
        const s = game[side]
        const roster = rosters[s.team_id] || []
        return (
          <div key={side} className="lg-editside">
            <div className="lg-editteam">
              <label className="lg-field">
                <span>{side === 'away' ? 'Top team (away)' : 'Bottom team (home)'}</span>
                <select value={s.team_id || ''} onChange={(e) => setSide(side, { team_id: e.target.value || null })}>
                  <option value="">{s.read_as ? `Pick a team (read “${s.read_as}”)` : 'Pick a team'}</option>
                  {teams.map((t) => <option key={t.id} value={t.id}>{t.full_name || t.name}</option>)}
                </select>
              </label>
              <div className="lg-field">
                <span>Periods</span>
                <div className="lg-quarters">
                  {s.quarters.map((q, i) => (
                    <input key={i} type="number" min="0" aria-label={`Period ${i + 1}`} value={q}
                      onChange={(e) => setSide(side, { quarters: s.quarters.map((x, j) => (j === i ? e.target.value : x)) })} />
                  ))}
                  <button type="button" className="lg-btn lg-btn-sm" onClick={() => setSide(side, { quarters: [...s.quarters, 0] })}>+ OT</button>
                  {s.quarters.length > 4 && (
                    <button type="button" className="lg-btn lg-btn-sm" onClick={() => setSide(side, { quarters: s.quarters.slice(0, -1) })}>− OT</button>
                  )}
                </div>
              </div>
              <label className="lg-field lg-scorefield">
                <span>Final</span>
                <input type="number" min="0" value={s.score} onChange={(e) => setSide(side, { score: e.target.value })} />
              </label>
            </div>

            {!s.lines ? (
              <div className="lg-nobox">
                <span className="lg-muted">No box score for this team. Upload their screenshot, or</span>
                <button type="button" className="lg-btn lg-btn-sm" onClick={() => setSide(side, { lines: [blankLine()] })}>type it in</button>
              </div>
            ) : (
              <div className="lg-tablewrap">
                <table className="lg-table lg-edittable">
                  <thead>
                    <tr>
                      <th>2K name</th>
                      <th>League player</th>
                      {STATS.map(([k, l]) => <th key={k} className="num">{l}</th>)}
                      <th aria-label="Remove" />
                    </tr>
                  </thead>
                  <tbody>
                    {s.lines.map((l, i) => {
                      const linked = l.player_id && !roster.some((p) => p.id === l.player_id)
                      return (
                        <tr key={i} className={l.player_id ? '' : 'is-unlinked'}>
                          <td><input className="lg-namein" value={l.player_name} onChange={(e) => setLine(side, i, { player_name: e.target.value })} /></td>
                          <td>
                            <select value={l.player_id || ''} onChange={(e) => {
                              const p = roster.find((x) => x.id === e.target.value)
                              setLine(side, i, { player_id: e.target.value || null, player_full_name: p?.name || null })
                            }}>
                              <option value="">Not linked</option>
                              {linked && <option value={l.player_id}>{l.player_full_name || 'Linked player'}</option>}
                              {roster.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                            </select>
                          </td>
                          {STATS.map(([k]) => (
                            <td key={k}>
                              <input type="number" min="0" className="lg-statin" aria-label={k} value={l[k]}
                                onChange={(e) => setLine(side, i, { [k]: e.target.value })} />
                            </td>
                          ))}
                          <td>
                            <button type="button" className="lg-btn lg-btn-sm" aria-label="Remove row"
                              onClick={() => setSide(side, { lines: s.lines.filter((_, j) => j !== i) })}>×</button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                <button type="button" className="lg-btn lg-btn-sm" onClick={() => setSide(side, { lines: [...s.lines, blankLine()] })}>+ Player</button>
              </div>
            )}
          </div>
        )
      })}

      {(warnings.length > 0 || initial.notes?.length > 0) && (
        <ul className="lg-checks">
          {[...(initial.notes || []), ...warnings].map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
      {error && <div className="lg-error">{error}</div>}

      <div className="lg-editoractions">
        <button type="button" className="lg-btn lg-btn-go" disabled={saving} onClick={() => save(false)}>
          {saving ? 'Saving…' : game.id ? 'Save changes' : 'Save game'}
        </button>
        {duplicate && (
          <button type="button" className="lg-btn" disabled={saving} onClick={() => save(true)}>Save anyway</button>
        )}
        <button type="button" className="lg-btn" disabled={saving} onClick={onDiscard}>{game.id ? 'Cancel' : 'Discard'}</button>
      </div>
    </section>
  )
}
