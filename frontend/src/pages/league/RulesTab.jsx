import { useCallback, useEffect, useRef, useState } from 'react'
import * as league from '../../utils/leagueApi'

// The league rulebook. Everyone in the league reads it; commissioners edit the
// text and the settings the site enforces. Numbers in the text are {tokens}
// filled from those settings, so the two can't drift apart.

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const SETTINGS = [
  { key: 'roster_size', label: 'Roster size', min: 5, max: 15, suffix: 'players' },
  { key: 'untouchables_per_team', label: 'Untouchables per team', min: 0, max: 8 },
  { key: 'sixth_man_min_minutes', label: '6th man minimum', min: 0, max: 48, suffix: 'min' },
  { key: 'bench_min_minutes', label: 'Rest of bench minimum', min: 0, max: 48, suffix: 'min' },
  { key: 'max_trade_teams', label: 'Most teams in a trade', min: 2, max: 3, suffix: 'teams' },
  { key: 'sim_weekday', label: 'Sim day', kind: 'weekday' },
  { key: 'sim_hour', label: 'Sim time (ET)', kind: 'hour' },
  { key: 'gameplan_lock_days', label: 'Lock day', kind: 'deadline' },
  { key: 'gameplan_lock_minute', label: 'Lock time (ET)', kind: 'time' },
  { key: 'lock_roster_moves', label: 'Trades & signings', kind: 'bool' },
]

// Lock times offered in the picker: every 30 minutes, plus 11:59 PM.
const LOCK_TIMES = [...Array.from({ length: 48 }, (_, i) => i * 30), 23 * 60 + 59]

function minuteLabel(m) {
  const h = Math.floor(m / 60)
  return `${h % 12 || 12}:${String(m % 60).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`
}

function hourLabel(h) {
  return `${h % 12 || 12}:00 ${h < 12 ? 'AM' : 'PM'}`
}

function settingText(def, value, all) {
  if (value === null || value === undefined) return '—'
  if (def.kind === 'weekday') return WEEKDAYS[value]
  if (def.kind === 'hour') return `${hourLabel(value)} ET`
  if (def.kind === 'deadline') return value === 0 ? `${WEEKDAYS[all.sim_weekday]} (sim day)` : WEEKDAYS[(all.sim_weekday - value + 7) % 7]
  if (def.kind === 'time') return `${minuteLabel(value)} ET`
  if (def.kind === 'bool') return value ? 'Lock with gameplans' : 'Stay open'
  return def.suffix ? `${value} ${def.suffix}` : String(value)
}

let newId = 0
const tempId = () => `new-${Date.now().toString(36)}-${(newId += 1)}`

export default function RulesTab({ onSettingsSaved }) {
  const [book, setBook] = useState(null)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState([])
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setBook(await league.getRules())
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const startEditing = () => {
    setDraft(book.rules.map(({ id, title, body }) => ({ id, title, body })))
    setEditing(true)
    setNote(null)
  }

  const saveText = async () => {
    setSaving(true)
    setError(null)
    try {
      const next = await league.saveRules(draft, book.version)
      setBook(next)
      setEditing(false)
      setNote('Rules saved.')
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (!book) return error ? <div className="lg-error">{error}</div> : <p className="lg-muted">Loading the rules…</p>

  return (
    <section className="lg-rules">
      {error && <div className="lg-error">{error}</div>}
      {note && <div className="lg-flash">{note}</div>}

      <SettingsPanel
        settings={book.settings}
        canEdit={book.can_edit}
        onSaved={async (msg) => {
          setNote(msg)
          await load()
          onSettingsSaved?.()
        }}
        onError={setError}
      />

      <div className="lg-rules-head">
        <div>
          <h2 className="lg-subhead">Rulebook</h2>
          {book.updated_at && (
            <p className="lg-muted lg-fineprint">
              Last changed {new Date(book.updated_at).toLocaleDateString()}{book.updated_by ? ` by ${book.updated_by}` : ''}.
            </p>
          )}
        </div>
        {book.can_edit && !editing && (
          <button type="button" className="lg-btn" onClick={startEditing}>Edit rules</button>
        )}
      </div>

      {editing ? (
        <RuleEditor
          draft={draft}
          setDraft={setDraft}
          tokens={book.tokens}
          saving={saving}
          onSave={saveText}
          onCancel={() => { setEditing(false); setError(null) }}
        />
      ) : (
        <ol className="lg-rulelist">
          {book.rules.map((r) => (
            <li key={r.id}>
              <h3>{r.title_rendered}</h3>
              {r.body_rendered.split(/\n{2,}/).map((para, i) => <p key={i}>{para}</p>)}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function SettingsPanel({ settings, canEdit, onSaved, onError }) {
  const [editing, setEditing] = useState(false)
  const [values, setValues] = useState({})
  const [saving, setSaving] = useState(false)

  const start = () => {
    setValues(Object.fromEntries(SETTINGS.map((d) => [d.key, settings[d.key]])))
    setEditing(true)
  }

  const save = async () => {
    setSaving(true)
    onError(null)
    try {
      const kindOf = Object.fromEntries(SETTINGS.map((d) => [d.key, d.kind]))
      const changed = Object.fromEntries(
        Object.entries(values)
          .map(([k, v]) => [k, kindOf[k] === 'bool' ? Boolean(v) : Number(v)])
          .filter(([k, v]) => v !== settings[k]),
      )
      if (Object.keys(changed).length) await league.updateLeagueSettings(changed)
      setEditing(false)
      onSaved(Object.keys(changed).length ? 'Settings saved. The rules below now use the new numbers.' : 'No settings changed.')
    } catch (err) {
      onError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="lg-settings">
      <div className="lg-rules-head">
        <div>
          <h2 className="lg-subhead">League settings</h2>
          <p className="lg-muted lg-fineprint">
            The site enforces these. The rulebook text uses them. The lock holds until the end of sim day.
          </p>
        </div>
        {canEdit && !editing && <button type="button" className="lg-btn" onClick={start}>Change settings</button>}
      </div>
      <dl className="lg-settinggrid">
        {SETTINGS.map((def) => (
          <div key={def.key} className="lg-setting">
            <dt><label htmlFor={`set-${def.key}`}>{def.label}</label></dt>
            <dd>
              {editing ? (
                <SettingInput def={def} value={values[def.key]} sim={values.sim_weekday}
                  onChange={(v) => setValues((s) => ({ ...s, [def.key]: v }))} />
              ) : settingText(def, settings[def.key], settings)}
            </dd>
          </div>
        ))}
      </dl>
      {editing && (
        <div className="lg-actions">
          <button type="button" className="lg-btn lg-btn-go" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save settings'}
          </button>
          <button type="button" className="lg-btn" onClick={() => setEditing(false)} disabled={saving}>Cancel</button>
        </div>
      )}
    </div>
  )
}

function SettingInput({ def, value, sim, onChange }) {
  const id = `set-${def.key}`
  if (def.kind === 'weekday') {
    return (
      <select id={id} value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
      </select>
    )
  }
  if (def.kind === 'hour') {
    return (
      <select id={id} value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{hourLabel(h)} ET</option>)}
      </select>
    )
  }
  if (def.kind === 'deadline') {
    return (
      <select id={id} value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {[0, 1, 2, 3, 4, 5, 6].map((n) => (
          <option key={n} value={n}>
            {WEEKDAYS[(sim - n + 7) % 7]} {n === 0 ? '(sim day)' : `(${n} day${n === 1 ? '' : 's'} before)`}
          </option>
        ))}
      </select>
    )
  }
  if (def.kind === 'time') {
    return (
      <select id={id} value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {LOCK_TIMES.map((m) => <option key={m} value={m}>{minuteLabel(m)} ET</option>)}
      </select>
    )
  }
  if (def.kind === 'bool') {
    return (
      <label className="lg-toggle" htmlFor={id}>
        <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        Lock with gameplans
      </label>
    )
  }
  return (
    <input id={id} type="number" min={def.min} max={def.max} value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
  )
}

function RuleEditor({ draft, setDraft, tokens, saving, onSave, onCancel }) {
  const lastBody = useRef(null)
  const update = (i, patch) => setDraft((list) => list.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const move = (i, d) => setDraft((list) => {
    const next = [...list]
    ;[next[i], next[i + d]] = [next[i + d], next[i]]
    return next
  })
  const [armed, setArmed] = useState(null)

  // Put a {token} at the cursor of the rule body that was last focused.
  const insertToken = (key) => {
    const target = lastBody.current
    if (!target) return
    const i = Number(target.dataset.index)
    const text = `{${key}}`
    const start = target.selectionStart ?? target.value.length
    const end = target.selectionEnd ?? start
    update(i, { body: target.value.slice(0, start) + text + target.value.slice(end) })
    requestAnimationFrame(() => {
      target.focus()
      target.setSelectionRange(start + text.length, start + text.length)
    })
  }

  return (
    <div className="lg-ruleedit">
      <div className="lg-tokens">
        <p className="lg-muted lg-fineprint">
          Click a value to insert it into the rule you're typing. It shows as the live number, so the text updates when the setting changes.
        </p>
        <div className="lg-tokenlist">
          {tokens.map((t) => (
            <button key={t.key} type="button" className="lg-token" onMouseDown={(e) => e.preventDefault()}
              onClick={() => insertToken(t.key)} title={t.label}>
              {t.label}: <strong>{t.value}</strong>
            </button>
          ))}
        </div>
      </div>

      <ol className="lg-ruleforms">
        {draft.map((r, i) => (
          <li key={r.id} className="lg-ruleform">
            <div className="lg-ruleform-top">
              <span className="lg-rulenum">{i + 1}</span>
              <input
                className="lg-ruletitle"
                value={r.title}
                placeholder="Rule title"
                aria-label={`Rule ${i + 1} title`}
                onChange={(e) => update(i, { title: e.target.value })}
              />
              <div className="lg-gp-order">
                <button type="button" aria-label="Move rule up" onClick={() => move(i, -1)} disabled={i === 0}>↑</button>
                <button type="button" aria-label="Move rule down" onClick={() => move(i, 1)} disabled={i === draft.length - 1}>↓</button>
              </div>
              <button
                type="button"
                className={`lg-btn lg-btn-sm${armed === r.id ? ' lg-btn-stop' : ''}`}
                onClick={() => {
                  if (armed === r.id) { setDraft((list) => list.filter((x) => x.id !== r.id)); setArmed(null) }
                  else { setArmed(r.id); setTimeout(() => setArmed((a) => (a === r.id ? null : a)), 3000) }
                }}
              >
                {armed === r.id ? 'Click again to delete' : 'Delete'}
              </button>
            </div>
            <textarea
              value={r.body}
              data-index={i}
              rows={Math.min(10, Math.max(3, Math.ceil((r.body || '').length / 90)))}
              placeholder="What the rule says. Leave a blank line between paragraphs."
              aria-label={`Rule ${i + 1} text`}
              onFocus={(e) => { lastBody.current = e.target }}
              onChange={(e) => update(i, { body: e.target.value })}
            />
          </li>
        ))}
      </ol>

      <button type="button" className="lg-btn lg-addteam"
        onClick={() => setDraft((list) => [...list, { id: tempId(), title: '', body: '' }])}>
        + Add a rule
      </button>

      <div className="lg-gp-savebar">
        <span className="lg-muted">Everyone in the league sees the rules as soon as you save.</span>
        <div className="lg-actions">
          <button type="button" className="lg-btn" onClick={onCancel} disabled={saving}>Cancel</button>
          <button type="button" className="lg-btn lg-btn-go" onClick={onSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save rules'}
          </button>
        </div>
      </div>
    </div>
  )
}
