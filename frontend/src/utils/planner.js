// Client for the build-planner service (the Node sidecar that wraps the WASM
// engine living in ../../../build_planner). Kept separate from utils/api.js
// because it targets a different origin/port than the Flask backend.
//
// Dev:  http://localhost:5180 (the `npm run serve` default in build_planner)
// Prod: VITE_PLANNER_BASE_URL, else same-origin (reverse-proxy /api/planner -> service)

function getPlannerBaseUrl() {
  if (import.meta.env.DEV) {
    return import.meta.env.VITE_PLANNER_BASE_URL || 'http://localhost:5180'
  }
  const prodUrl = import.meta.env.VITE_PLANNER_BASE_URL
  return prodUrl ? prodUrl.replace(/\/$/, '') : ''
}

function plannerUrl(path) {
  const base = getPlannerBaseUrl()
  if (!path.startsWith('/')) path = '/' + path
  return base + path
}

/**
 * Fetch static planner metadata: positions, attribute categories/labels, value ranges.
 * @returns {Promise<Object>}
 */
export async function getPlannerMeta() {
  const res = await fetch(plannerUrl('/api/planner/meta'))
  if (!res.ok) throw new Error(`Planner meta failed: HTTP ${res.status}`)
  return res.json()
}

/**
 * Recompute the full derived state for a build.
 * @param {Object} build - { position, height, weight, wingspan, attributes }
 * @param {AbortSignal} [signal] - optional abort signal (for debounced/cancelled calls)
 * @returns {Promise<Object>} OVR, maxOvr, buildName, per-attribute soft/physical caps,
 *   cap-breaker tiers, badges, takeovers, animations.
 */
export async function recomputeBuild(build, signal = null) {
  const res = await fetch(plannerUrl('/api/planner/recompute'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(build),
    signal: signal || undefined,
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try { msg = (await res.json()).error || msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json()
}

/**
 * Fetch the qualifying animations for a build, grouped by category -> subcategory.
 * Separate from recompute so the large list is only fetched when the user views it.
 * @param {Object} build - { position, height, weight, wingspan, attributes }
 * @param {AbortSignal} [signal]
 * @returns {Promise<{ categories: Array<{ key, label, available, total, groups }> }>}
 */
/**
 * Fetch the full animation catalog (every animation + its requirements), with
 * no qualification applied.
 *
 * Requirements are static, so this is fetched once per session and cached in
 * module scope. Qualification is then computed locally against the build's
 * effective attributes — which is what lets the planner show unavailable
 * animations greyed out, and update requirement tooltips live while an
 * attribute is being dragged, with no network round-trip.
 *
 * @returns {Promise<{categories: Array<{key, label}>, animations: Array<{id, name, category, subCategory, requirements, minHeight, maxHeight}>}>}
 */
let _catalogPromise = null
export function getAnimationCatalog() {
  if (!_catalogPromise) {
    _catalogPromise = fetch(plannerUrl('/api/planner/animations/catalog'))
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .catch((e) => {
        // Don't cache a failure — let the next mount retry.
        _catalogPromise = null
        throw e
      })
  }
  return _catalogPromise
}

export async function getAnimations(build, signal = null) {
  const res = await fetch(plannerUrl('/api/planner/animations'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(build),
    signal: signal || undefined,
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try { msg = (await res.json()).error || msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json()
}

/**
 * Fetch the curated template catalog. Returns the whole set in one call (a few
 * hundred entries, ~38 KB gzipped) so the gallery can filter and sort locally.
 * Each entry carries its full attribute vector, so "start from this build"
 * needs no follow-up request.
 * @returns {Promise<{ templates: Array, stats: Object|null }>}
 */
export async function getTemplates() {
  const res = await fetch(plannerUrl('/api/planner/templates'))
  if (!res.ok) throw new Error(`Planner templates failed: HTTP ${res.status}`)
  return res.json()
}

/**
 * Enrich arbitrary builds (our own DB-flagged templates) into the same card
 * shape as the curated catalog — OVR, archetype, badges, category scores.
 * @param {Array<{id, name, position, height, weight, wingspan, attributes}>} builds
 * @returns {Promise<{ templates: Array }>}
 */
export async function summarizeBuilds(builds) {
  const res = await fetch(plannerUrl('/api/planner/summarize'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ builds }),
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try { msg = (await res.json()).error || msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json()
}

/** Format inches as feet'inches" (e.g. 79 -> 6'7"). */
export function formatHeight(inches) {
  return `${Math.floor(inches / 12)}'${inches % 12}"`
}
