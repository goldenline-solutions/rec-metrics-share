import { useCallback, useEffect, useMemo, useState } from 'react'
import * as league from '../../utils/leagueApi'

// Commissioner-only: every gameplan field a GM changed that still has to be
// set in 2K. Ticking a row means "done in the game". Repeat edits to one field
// arrive already merged, so each row is one thing to change.

function utcDate(iso) {
  if (!iso) return null
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`)
}

function ago(iso) {
  const d = utcDate(iso)
  if (!d) return ''
  const mins = Math.round((Date.now() - d.getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

export default function GameplanChangesTab({ onCountChange }) {
  const [changes, setChanges] = useState([])
  const [showDone, setShowDone] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [pending, setPending] = useState(() => new Set())

  const load = useCallback(async () => {
    setError(null)
    try {
      const data = await league.getGameplanChanges({ includeDone: showDone })
      setChanges(data.changes || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [showDone])

  useEffect(() => {
    load()
    // GMs keep editing until Thursday night; keep the list current while it's open.
    const timer = setInterval(load, 60000)
    return () => clearInterval(timer)
  }, [load])

  const openCount = changes.filter((c) => !c.done).length
  const openTeams = new Set(changes.filter((c) => !c.done).map((c) => c.team_id)).size
  useEffect(() => { onCountChange?.(openCount) }, [openCount, onCountChange])

  const byTeam = useMemo(() => {
    const groups = new Map()
    for (const c of changes) {
      if (!groups.has(c.team_id)) groups.set(c.team_id, { team: c.team, settings: [], rotation: [] })
      groups.get(c.team_id)[c.is_rotation ? 'rotation' : 'settings'].push(c)
    }
    return [...groups.values()]
  }, [changes])

  const mark = async (ids, done) => {
    setPending((s) => new Set([...s, ...ids]))
    setChanges((list) => list.map((c) => (ids.includes(c.id) ? { ...c, done } : c)))
    try {
      await league.markGameplanChanges(ids, done)
      if (!showDone && done) setChanges((list) => list.filter((c) => !ids.includes(c.id)))
    } catch (err) {
      setError(err.message)
      load()
    } finally {
      setPending((s) => { const n = new Set(s); ids.forEach((id) => n.delete(id)); return n })
    }
  }

  if (loading) return <p className="lg-muted">Loading changes…</p>

  return (
    <section className="lg-changes">
      <div className="lg-changes-head">
        <div>
          <h2 className="lg-subhead">Change in 2K</h2>
          <p className="lg-muted lg-fineprint">
            {openCount
              ? `${openCount} change${openCount === 1 ? '' : 's'} across ${openTeams} team${openTeams === 1 ? '' : 's'}. Tick each one once it's set in the game.`
              : 'Nothing to change. New gameplan edits show up here.'}
          </p>
        </div>
        <div className="lg-actions">
          <label className="lg-toggle">
            <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} />
            Show done
          </label>
          <button type="button" className="lg-btn" onClick={load}>Refresh</button>
        </div>
      </div>

      {error && <div className="lg-error">{error}</div>}

      {byTeam.length === 0 && (
        <div className="lg-empty">
          <p>All caught up.</p>
          <p className="lg-muted lg-fineprint">When a GM saves a gameplan, each setting they changed lands here as old → new.</p>
        </div>
      )}

      <div className="lg-changeteams">
        {byTeam.map((group) => {
          const open = [...group.settings, ...group.rotation].filter((c) => !c.done)
          return (
            <article key={group.team} className={`lg-changeteam${open.length ? '' : ' is-clear'}`}>
              <header className="lg-changeteam-head">
                <h3>{group.team}</h3>
                <span className="lg-muted">{open.length ? `${open.length} to change` : 'done'}</span>
                {open.length > 1 && (
                  <button type="button" className="lg-btn lg-btn-sm" onClick={() => mark(open.map((c) => c.id), true)}>
                    Mark all done
                  </button>
                )}
              </header>
              {group.settings.length > 0 && <ChangeList rows={group.settings} mark={mark} pending={pending} />}
              {group.rotation.length > 0 && (
                <>
                  <p className="lg-changegroup">Rotation</p>
                  <ChangeList rows={group.rotation} mark={mark} pending={pending} />
                </>
              )}
            </article>
          )
        })}
      </div>
    </section>
  )
}

function ChangeList({ rows, mark, pending }) {
  return (
    <ul className="lg-changelist">
      {rows.map((c) => (
        <li key={c.id} className={c.done ? 'is-done' : ''}>
          <label className="lg-changecheck">
            <input
              type="checkbox"
              checked={c.done}
              disabled={pending.has(c.id)}
              onChange={(e) => mark([c.id], e.target.checked)}
              aria-label={`${c.field}: mark ${c.done ? 'not done' : 'done'}`}
            />
          </label>
          <span className="lg-changefield">{c.field}</span>
          <span className="lg-changevalue">
            <span className="lg-old">{c.old_value ?? 'not set'}</span>
            <span className="lg-arrow-sm" aria-hidden="true">→</span>
            <span className="lg-new">{c.new_value ?? 'cleared'}</span>
          </span>
          <span className="lg-changeby">
            {c.by_commissioner ? 'Commissioner' : c.by || 'GM'} · {ago(c.updated_at || c.created_at)}
          </span>
        </li>
      ))}
    </ul>
  )
}
