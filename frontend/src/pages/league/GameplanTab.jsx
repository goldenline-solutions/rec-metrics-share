import { useCallback, useEffect, useMemo, useState } from 'react'
import * as league from '../../utils/leagueApi'

// The weekly gameplan: rotation minutes, coaching sliders, sim emphasis.
// Allowed values come from the server (mynba_gameplan_options.json), and the
// server re-checks everything on save. The rules here only give live feedback.

function utcDate(iso) {
  if (!iso) return null
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`)
}

function listedPositions(row) {
  return new Set(
    [row.position, row.secondary_position]
      .flatMap((p) => (p || '').toUpperCase().split(/[/,\s]+/))
      .filter(Boolean),
  )
}

// A starter must be listed at their slot (primary or secondary). Unknown positions pass.
function outOfPosition(row, index, rules) {
  const slots = rules?.starter_slots || []
  if (index >= slots.length) return false
  const listed = listedPositions(row)
  return listed.size > 0 && !listed.has(slots[index])
}

function rotationProblems(rows, rules) {
  if (!rules) return []
  const out = []
  rows.slice(0, rules.starter_slots.length).forEach((r, i) => {
    if (outOfPosition(r, i, rules)) {
      out.push(`${r.name} is listed ${[...listedPositions(r)].sort().join('/')} and can't start at ${rules.starter_slots[i]}.`)
    }
  })
  const total = rows.reduce((sum, r) => sum + r.minutes, 0)
  if (total !== rules.team_minutes) {
    const diff = rules.team_minutes - total
    out.push(`Minutes add up to ${total}, not ${rules.team_minutes}. ${diff > 0 ? 'Add' : 'Remove'} ${Math.abs(diff)}.`)
  }
  const six = rules.starter_slots.length
  if (rows.length > six && rows[six].minutes < rules.sixth_man_min) {
    out.push(`6th man needs at least ${rules.sixth_man_min} minutes.`)
  }
  for (let i = six + 1; i < Math.min(rows.length, rules.roster_size || 8); i += 1) {
    if (rows[i].minutes < rules.bench_min) out.push(`Bench ${i + 1} needs at least ${rules.bench_min} minutes.`)
  }
  return out
}

function slotLabel(i, rules) {
  const starters = rules?.starter_slots || ['PG', 'SG', 'SF', 'PF', 'C']
  if (i < starters.length) return starters[i]
  if (i === starters.length) return '6th'
  return String(i + 1)
}

function minFor(i, rules) {
  if (!rules) return 0
  const six = rules.starter_slots.length
  if (i === six) return rules.sixth_man_min
  if (i > six && i < (rules.roster_size || 8)) return rules.bench_min
  return 0
}

export default function GameplanTab({ teams, myTeam, isCommish, onSaved }) {
  const [options, setOptions] = useState(null)
  const [teamId, setTeamId] = useState(myTeam?.id || '')
  const [plan, setPlan] = useState(null)
  const [settings, setSettings] = useState({})
  const [rows, setRows] = useState([])
  const [error, setError] = useState(null)
  const [stale, setStale] = useState(false)
  const [saving, setSaving] = useState(false)
  const [savedNote, setSavedNote] = useState(null)
  const [untouchBusy, setUntouchBusy] = useState(null)

  useEffect(() => {
    league.getGameplanOptions().then(setOptions).catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    if (!teamId && teams.length) setTeamId(myTeam?.id || teams[0].id)
  }, [teams, myTeam, teamId])

  const loadPlan = useCallback(async () => {
    if (!teamId) return
    setError(null)
    setStale(false)
    try {
      const data = await league.getTeamGameplan(teamId)
      setPlan(data.gameplan)
      setSettings(data.gameplan.settings || {})
      setRows(data.gameplan.rotation || [])
    } catch (err) {
      setError(err.message)
    }
  }, [teamId])

  useEffect(() => { loadPlan() }, [loadPlan])

  const rules = options?.rules
  const lock = options?.lock
  const canEdit = Boolean(plan?.can_edit)
  const problems = useMemo(() => rotationProblems(rows, rules), [rows, rules])
  const total = rows.reduce((sum, r) => sum + r.minutes, 0)
  const remaining = (rules?.team_minutes ?? 240) - total

  const dirty = useMemo(() => {
    if (!plan) return false
    const savedRows = plan.rotation || []
    const rotationChanged = rows.length !== savedRows.length ||
      rows.some((r, i) => r.player_id !== savedRows[i]?.player_id || r.minutes !== savedRows[i]?.minutes)
    const keys = new Set([...Object.keys(settings), ...Object.keys(plan.settings || {})])
    const settingsChanged = [...keys].some((k) => (settings[k] ?? null) !== ((plan.settings || {})[k] ?? null))
    return rotationChanged || settingsChanged
  }, [plan, rows, settings])

  const setMinutes = (index, value) => {
    const max = rules?.max_player_minutes ?? 48
    const minutes = Math.max(0, Math.min(max, Number.isFinite(value) ? Math.round(value) : 0))
    setRows((list) => list.map((r, i) => (i === index ? { ...r, minutes } : r)))
    setSavedNote(null)
  }

  const moveRow = (index, delta) => {
    const to = index + delta
    if (to < 0 || to >= rows.length) return
    setRows((list) => {
      const next = [...list]
      ;[next[index], next[to]] = [next[to], next[index]]
      return next
    })
    setSavedNote(null)
  }

  const setSetting = (key, value) => {
    setSettings((s) => ({ ...s, [key]: value }))
    setSavedNote(null)
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      // Settings left blank are sent as null so the server clears them too.
      const keys = new Set([...Object.keys(settings), ...Object.keys(plan.settings || {})])
      const outSettings = Object.fromEntries([...keys].map((k) => [k, settings[k] ?? null]))
      const data = await league.saveTeamGameplan(teamId, {
        settings: outSettings,
        rotation: rows.map((r) => ({ player_id: r.player_id, minutes: r.minutes })),
        baseVersion: plan.version,
      })
      setPlan(data.gameplan)
      setSettings(data.gameplan.settings || {})
      setRows(data.gameplan.rotation || [])
      const n = data.changes.length
      setSavedNote(n ? `Saved. ${n} change${n === 1 ? '' : 's'} sent to the commissioner.` : 'Saved. Nothing changed.')
      onSaved?.()
    } catch (err) {
      if (err.code === 'stale') setStale(true)
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const toggleUntouchable = async (row) => {
    setUntouchBusy(row.player_id)
    setError(null)
    try {
      await league.setUntouchable(row.name, !row.is_untouchable)
      setRows((list) => list.map((r) => (r.player_id === row.player_id ? { ...r, is_untouchable: !r.is_untouchable } : r)))
    } catch (err) {
      setError(err.message)
    } finally {
      setUntouchBusy(null)
    }
  }

  if (!options || !plan) {
    return error ? <div className="lg-error">{error}</div> : <p className="lg-muted">Loading the gameplan…</p>
  }

  const fieldsBy = (section) => options.fields.filter((f) => f.section === section)
  const isMine = myTeam && myTeam.id === teamId
  const untouchCount = rows.filter((r) => r.is_untouchable).length
  const untouchLimit = rules.untouchables_per_team ?? 2

  return (
    <section className="lg-gameplan">
      <div className="lg-gp-head">
        <label className="lg-field lg-gp-team">
          <span>Team</span>
          <select value={teamId} onChange={(e) => { setTeamId(e.target.value); setSavedNote(null) }}>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>{t.name}{myTeam?.id === t.id ? ' (yours)' : ''}</option>
            ))}
          </select>
        </label>
        <LockBanner lock={lock} isCommish={isCommish} />
      </div>

      {!canEdit && (
        <div className="lg-notice">
          {isMine && lock?.locked
            ? 'Gameplans are locked until after the sim. Ask a commissioner if something has to change.'
            : 'View only. You can edit your own team’s gameplan.'}
        </div>
      )}
      {error && (
        <div className="lg-error">
          {error}
          {stale && <button type="button" className="lg-btn lg-btn-sm lg-gp-reload" onClick={loadPlan}>Reload</button>}
        </div>
      )}

      <div className="lg-gp-grid">
        <div className="lg-gp-panel lg-gp-rotation">
          <div className="lg-gp-panelhead">
            <h2 className="lg-subhead">Rotation</h2>
            <span className={`lg-gp-remaining${remaining === 0 ? ' is-ok' : ' is-off'}`}>
              Remaining minutes: <strong>{remaining}</strong>
            </span>
          </div>
          <p className="lg-muted lg-fineprint">
            Top five start, each at a position they're listed at. 6th man plays at least {rules.sixth_man_min}; bench {rules.starter_slots.length + 2}–{rules.roster_size} at least {rules.bench_min}. Use ↑ ↓ to change order.
          </p>
          <div className="lg-tablewrap">
            <table className="lg-table lg-gp-table">
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Player</th>
                  <th className="lg-gp-wide">Pos</th>
                  <th className="num lg-gp-wide">OVR</th>
                  <th className="lg-gp-mincol">Minutes</th>
                  {canEdit && <th aria-label="Order" />}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const floor = minFor(i, rules)
                  const low = floor > 0 && r.minutes < floor
                  const misplaced = outOfPosition(r, i, rules)
                  return (
                    <tr key={r.player_id} className={i === rules.starter_slots.length - 1 ? 'lg-gp-lastStarter' : ''}>
                      <td className={`lg-gp-slot${misplaced ? ' is-misplaced' : ''}`} title={misplaced ? 'Out of position' : undefined}>
                        {slotLabel(i, rules)}{misplaced && <span aria-label="out of position"> ✕</span>}
                      </td>
                      <td>
                        <span className="lg-gp-name">{r.name}</span>
                        <span className="lg-gp-meta">
                          {r.position || '—'}{r.secondary_position ? `/${r.secondary_position}` : ''}{r.ovr ? ` · ${r.ovr}` : ''}
                        </span>
                        {(isMine || isCommish) ? (
                          <button
                            type="button"
                            className={`lg-gp-untouch${r.is_untouchable ? ' is-on' : ''}`}
                            onClick={() => toggleUntouchable(r)}
                            disabled={untouchBusy === r.player_id || (!r.is_untouchable && untouchCount >= untouchLimit)}
                            title={r.is_untouchable ? 'Untouchable: can’t be traded. Click to clear.' : 'Mark untouchable (can’t be traded)'}
                          >
                            {r.is_untouchable ? 'Untouchable' : '+ Untouchable'}
                          </button>
                        ) : r.is_untouchable && <span className="lg-gp-untouch is-on">Untouchable</span>}
                      </td>
                      <td className="lg-gp-pos lg-gp-wide">
                        {r.position || '—'}
                        {r.secondary_position && <span className="lg-faint">/{r.secondary_position}</span>}
                      </td>
                      <td className="num lg-gp-wide">{r.ovr ?? '—'}</td>
                      <td>
                        {canEdit ? (
                          <div className={`lg-gp-stepper${low ? ' is-low' : ''}`}>
                            <button type="button" aria-label={`Less time for ${r.name}`} onClick={() => setMinutes(i, r.minutes - 1)} disabled={r.minutes <= 0}>▼</button>
                            <input
                              type="number"
                              inputMode="numeric"
                              min="0"
                              max={rules.max_player_minutes}
                              value={r.minutes}
                              aria-label={`Minutes for ${r.name}`}
                              onChange={(e) => setMinutes(i, parseInt(e.target.value, 10))}
                            />
                            <button type="button" aria-label={`More time for ${r.name}`} onClick={() => setMinutes(i, r.minutes + 1)} disabled={r.minutes >= rules.max_player_minutes}>▲</button>
                          </div>
                        ) : (
                          <span className={`lg-gp-minread${low ? ' is-low' : ''}`}>{r.minutes}</span>
                        )}
                      </td>
                      {canEdit && (
                        <td className="lg-gp-order">
                          <button type="button" aria-label={`Move ${r.name} up`} onClick={() => moveRow(i, -1)} disabled={i === 0}>↑</button>
                          <button type="button" aria-label={`Move ${r.name} down`} onClick={() => moveRow(i, 1)} disabled={i === rows.length - 1}>↓</button>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {(isMine || isCommish) && (
            <p className="lg-muted lg-fineprint">Untouchables: {untouchCount} of {untouchLimit}. Untouchable players can’t be traded.</p>
          )}
          {problems.length > 0 && (
            <ul className="lg-gp-problems">
              {problems.map((p) => <li key={p}>{p}</li>)}
            </ul>
          )}
        </div>

        <div className="lg-gp-side">
          {options.sections.map((section) => (
            <div key={section.key} className="lg-gp-panel">
              <h2 className="lg-subhead">{section.label}</h2>
              <div className="lg-gp-fields">
                {fieldsBy(section.key).map((f) => (
                  <SettingField key={f.key} field={f} value={settings[f.key]} onChange={setSetting} disabled={!canEdit} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {canEdit && (
        <div className="lg-gp-savebar">
          <span className="lg-muted">
            {savedNote || (dirty ? 'Unsaved changes.' : plan.updated_at
              ? `Last saved ${utcDate(plan.updated_at).toLocaleString()}${plan.updated_by ? ` by ${plan.updated_by}` : ''}.`
              : 'Not submitted yet.')}
          </span>
          <button
            type="button"
            className="lg-btn lg-btn-go"
            onClick={save}
            disabled={saving || !dirty || problems.length > 0}
            title={problems.length ? 'Fix the rotation first' : undefined}
          >
            {saving ? 'Saving…' : 'Save gameplan'}
          </button>
        </div>
      )}
    </section>
  )
}

function LockBanner({ lock, isCommish }) {
  if (!lock) return null
  if (lock.locked) {
    return (
      <div className="lg-gp-lock is-locked">
        <strong>Locked</strong> until after the sim{lock.override ? ' (set by a commissioner)' : ''}.
        {isCommish && ' You can still edit.'}
      </div>
    )
  }
  const deadline = utcDate(lock.deadline_utc)
  const hours = deadline ? Math.max(0, Math.floor((deadline.getTime() - Date.now()) / 3600000)) : null
  return (
    <div className={`lg-gp-lock${hours !== null && hours < 24 ? ' is-soon' : ''}`}>
      Due <strong>{lock.deadline_label}</strong>
      {hours !== null && <span className="lg-muted"> · {hours >= 48 ? `${Math.floor(hours / 24)} days left` : `${hours}h left`}</span>}
    </div>
  )
}

function SettingField({ field, value, onChange, disabled }) {
  const id = `gp-${field.key}`
  if (field.kind === 'choice') {
    return (
      <label className="lg-field" htmlFor={id}>
        <span>{field.label}</span>
        <select id={id} value={value ?? ''} disabled={disabled} onChange={(e) => onChange(field.key, e.target.value || null)}>
          <option value="">Not set</option>
          {field.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </label>
    )
  }
  const unset = value === undefined || value === null
  const mid = Math.round((field.min + field.max) / 2)
  return (
    <div className={`lg-field lg-gp-slider${unset ? ' is-unset' : ''}`}>
      <span>
        <label htmlFor={id}>{field.label}</label>
        <output htmlFor={id}>{unset ? 'not set' : value}</output>
      </span>
      <input
        id={id}
        type="range"
        min={field.min}
        max={field.max}
        step="1"
        value={unset ? mid : value}
        disabled={disabled}
        onChange={(e) => onChange(field.key, Number(e.target.value))}
      />
      <span className="lg-gp-range"><span>{field.min}</span>{!unset && !disabled && <button type="button" onClick={() => onChange(field.key, null)}>Clear</button>}<span>{field.max}</span></span>
    </div>
  )
}
