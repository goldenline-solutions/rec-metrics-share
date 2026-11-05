import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PageLayout from '../components/PageLayout'
import BuilderTabs from '../components/BuilderTabs'
import Card from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import EmptyState from '../components/ui/EmptyState'
import Seo from '../components/Seo'
import { Events } from '../utils/analytics'
import { getTemplateBuilds } from '../utils/api'
import { getPlannerMeta, getTemplates, summarizeBuilds, formatHeight } from '../utils/planner'
import { POSITIONS } from '../utils/positionLimits'
import { TEMPLATE_SORTS, templateComparator, dbBuildToSummarizeInput } from '../utils/buildTemplates'
import { tierVariant, tierLabel } from '../utils/badgeTiers'
import './TemplatesPage.css'

const CATEGORY_ORDER = ['Finishing', 'Shooting', 'Playmaking', 'Defense', 'Rebounding', 'Physicals']
const deCamel = (s) => s.replace(/([a-z0-9])([A-Z])/g, '$1 $2')

// The full selectable height span across every position (5'9" – 7'4").
const HEIGHT_MIN = 69
const HEIGHT_MAX = 88
const HEIGHT_OPTIONS = Array.from({ length: HEIGHT_MAX - HEIGHT_MIN + 1 }, (_, i) => HEIGHT_MIN + i)

export default function TemplatesPage() {
  const navigate = useNavigate()

  const [templates, setTemplates] = useState(null)
  const [error, setError] = useState(null)
  const [position, setPosition] = useState('all')
  const [minHeight, setMinHeight] = useState(HEIGHT_MIN)
  const [maxHeight, setMaxHeight] = useState(HEIGHT_MAX)
  const [sortKey, setSortKey] = useState('badgeScore')
  const [expanded, setExpanded] = useState({})

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const [meta, catalog] = await Promise.all([getPlannerMeta(), getTemplates()])

        // Our own flagged builds are optional garnish — if that call fails (not
        // logged in, backend down) the curated catalog still renders.
        let dbTemplates = []
        try {
          const { builds } = await getTemplateBuilds()
          const inputs = (builds || [])
            .map((b) => dbBuildToSummarizeInput(b, meta.labels))
            .filter(Boolean)
          if (inputs.length) dbTemplates = (await summarizeBuilds(inputs)).templates || []
        } catch { /* curated catalog only */ }

        if (!cancelled) setTemplates([...dbTemplates, ...(catalog.templates || [])])
      } catch (e) {
        if (!cancelled) setError(e.message)
      }
    }

    load()
    return () => { cancelled = true }
  }, [])

  const visible = useMemo(() => {
    if (!templates) return []
    const lo = Math.min(minHeight, maxHeight)
    const hi = Math.max(minHeight, maxHeight)
    return templates
      .filter((t) => position === 'all' || t.position === position)
      .filter((t) => t.height >= lo && t.height <= hi)
      .sort(templateComparator(sortKey))
  }, [templates, position, minHeight, maxHeight, sortKey])

  const toggle = (id) => setExpanded((m) => ({ ...m, [id]: !m[id] }))
  const startFrom = (t) => {
    Events.startedFromTemplate({ template_id: t.id, source: t.source, position: t.position })
    navigate(`/builds/new?template=${t.source === 'db' ? 'db' : 'lab'}:${encodeURIComponent(t.id)}`)
  }

  if (error) {
    return (
      <PageLayout title="Builder">
      <BuilderTabs />
        <div className="error-message">
          <strong>Template service unavailable:</strong> {error}
          <div className="tpl-hint">Start it with <code>npm run serve</code> in the build_planner folder.</div>
        </div>
      </PageLayout>
    )
  }

  if (!templates) return <PageLayout title="Builder">
      <BuilderTabs />Loading templates…</PageLayout>

  return (
    <PageLayout title="Builder" className="tpl-page">
      <Seo
        title="NBA 2K26 Template Builds — Browse & Customize | RecMetrics"
        description="Browse proven NBA 2K26 template builds by position, height, and badge quality. Start from any template and customize it in the build planner."
        path="/builds/templates"
      />
      <BuilderTabs />
      <Card className="tpl-controls">
        <div className="tpl-controls-row">
          <div className="tpl-field">
            <label>Position</label>
            <div className="tpl-segmented">
              <button className={`tpl-seg-btn ${position === 'all' ? 'active' : ''}`} onClick={() => setPosition('all')}>All</button>
              {POSITIONS.map((p) => (
                <button key={p} className={`tpl-seg-btn ${position === p ? 'active' : ''}`} onClick={() => setPosition(p)}>{p}</button>
              ))}
            </div>
          </div>

          <div className="tpl-field">
            <label htmlFor="tpl-min-height">Height</label>
            <div className="tpl-height-range">
              <select id="tpl-min-height" value={minHeight} onChange={(e) => setMinHeight(Number(e.target.value))}>
                {HEIGHT_OPTIONS.map((h) => <option key={h} value={h}>{formatHeight(h)}</option>)}
              </select>
              <span className="dim">to</span>
              <select value={maxHeight} onChange={(e) => setMaxHeight(Number(e.target.value))}>
                {HEIGHT_OPTIONS.map((h) => <option key={h} value={h}>{formatHeight(h)}</option>)}
              </select>
            </div>
          </div>

          <div className="tpl-field">
            <label htmlFor="tpl-sort">Sort by</label>
            <select id="tpl-sort" value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
              {TEMPLATE_SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>

          <div className="tpl-count">
            <strong>{visible.length}</strong> template{visible.length === 1 ? '' : 's'}
            <span className="tpl-credit">Courtesy of RecMetrics</span>
          </div>
        </div>
      </Card>

      {visible.length === 0 ? (
        <EmptyState title="No templates match" message="Try widening the height range or clearing the position filter." />
      ) : (
        <div className="tpl-grid">
          {visible.map((t) => {
            const open = !!expanded[t.id]
            const headroom = Math.floor(t.headroom)
            return (
              <Card className={`tpl-card ${open ? 'open' : ''}`} key={`${t.source}-${t.id}`}>
                <div className="tpl-card-head">
                  <div className="tpl-card-title">
                    <h3>{t.name}</h3>
                    {t.archetype && <span className="tpl-archetype">{t.archetype}</span>}
                  </div>
                  <div className="tpl-card-ovr">
                    <span className="tpl-ovr-num">{Math.round(t.ovr)}</span>
                    <span className="tpl-ovr-label">OVR</span>
                  </div>
                </div>

                <div className="tpl-pills">
                  <span className="tpl-pos-pill">{t.position}</span>
                  <span className="tpl-phys">{formatHeight(t.height)} · {t.weight} lb · {formatHeight(t.wingspan)} WS</span>
                  {t.source === 'db' && <span className="tpl-source-pill">Community</span>}
                </div>

                {headroom >= 1 && (
                  <div className="tpl-headroom" title="These templates land just under the cap, so you have points left to spend in the planner.">
                    +{headroom} OVR of room to customize
                  </div>
                )}

                <div className="tpl-attrs">
                  {t.topAttributes.map((a) => (
                    <span key={a.key} className="tpl-attr-chip">{a.label} <strong>{a.value}</strong></span>
                  ))}
                </div>

                <div className="tpl-cats">
                  {CATEGORY_ORDER.filter((c) => t.categoryScores[c] != null).map((c) => (
                    <div className="tpl-cat" key={c}>
                      <span className="tpl-cat-name">{c}</span>
                      <span className="tpl-cat-bar"><span className="tpl-cat-fill" style={{ width: `${Math.max(0, Math.min(100, ((t.categoryScores[c] - 25) / 74) * 100))}%` }} /></span>
                      <span className="tpl-cat-val">{t.categoryScores[c]}</span>
                    </div>
                  ))}
                </div>

                <div className="tpl-badge-counts">
                  {['Legend', 'HallOfFame', 'Gold'].filter((tier) => t.badgeCounts[tier] > 0).map((tier) => (
                    <Badge key={tier} variant={tierVariant(tier)}>{t.badgeCounts[tier]} {tierLabel(tier)}</Badge>
                  ))}
                  <span className="tpl-badge-total">{t.badgeCounts.total} badges</span>
                </div>

                {open && (
                  <div className="tpl-detail">
                    <div className="tpl-detail-title">Best badges</div>
                    <div className="tpl-badge-list">
                      {t.badges.map((b) => (
                        <span key={b.name} className="tpl-badge-item">
                          {deCamel(b.name)} <Badge variant={tierVariant(b.level)}>{tierLabel(b.level)}</Badge>
                        </span>
                      ))}
                    </div>
                    <div className="tpl-detail-title">Animations unlocked</div>
                    <div className="dim">{t.animationCount} available at these attributes</div>
                  </div>
                )}

                <div className="tpl-card-actions">
                  <button className="tpl-btn primary" onClick={() => startFrom(t)}>Start from this build</button>
                  <button className="tpl-btn" onClick={() => toggle(t.id)}>{open ? 'Less' : 'Details'}</button>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </PageLayout>
  )
}
