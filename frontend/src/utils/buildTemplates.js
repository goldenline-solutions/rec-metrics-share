// Helpers shared by the template gallery and the planner.
//
// The two template sources store builds differently: the planner service returns
// attributes keyed by their engine key (`ShotThree`), while builds saved to our
// DB store them by display label (`Three-Point Shot`) with heights as strings
// (`6'8"`). These helpers convert both into the shape BuildPlannerPage holds in
// state: { position, height, weight, wingspan, attributes: { key: value } }.

/** Parse a displayed height (`6'8"`, `6'8`) into inches. Inverse of formatHeight. */
export function parseHeightString(text) {
  if (typeof text === 'number') return Math.round(text)
  const m = String(text ?? '').replace(/"/g, '').trim().match(/^(\d+)'\s*(\d+)/)
  if (!m) return null
  return parseInt(m[1], 10) * 12 + parseInt(m[2], 10)
}

/**
 * Build a label -> attribute-key lookup from the planner meta's key -> label map.
 * Matching is done on a normalized form so punctuation drift ("Mid-Range Shot"
 * vs "Mid Range Shot") doesn't drop an attribute.
 */
export function makeLabelToKey(labels) {
  const map = {}
  const norm = (s) => String(s).toLowerCase().replace(/[^a-z0-9]/g, '')
  for (const [key, label] of Object.entries(labels || {})) {
    map[norm(label)] = key
    map[norm(key)] = key
  }
  return { get: (label) => map[norm(label)] ?? null }
}

/** Turn a catalog template into planner state. */
export function templateToPlannerBuild(template) {
  return {
    position: template.position,
    height: template.height,
    weight: template.weight,
    wingspan: template.wingspan,
    attributes: { ...template.attributes },
  }
}

/**
 * Turn a build fetched from our own API into planner state.
 * Returns null when the record lacks the physicals the planner needs.
 */
export function dbBuildToPlannerBuild(build, labels) {
  const height = parseHeightString(build?.height)
  if (!height) return null

  const lookup = makeLabelToKey(labels)
  const attributes = {}
  for (const rows of Object.values(build.attributes_by_category || {})) {
    for (const row of rows) {
      const key = lookup.get(row.name)
      if (key && Number.isFinite(Number(row.current))) attributes[key] = Number(row.current)
    }
  }

  return {
    position: build.position || 'PG',
    height,
    weight: Number(build.weight_lbs) || 0,
    wingspan: parseHeightString(build?.wingspan) ?? height,
    attributes,
  }
}

/**
 * Shape a DB build into the payload the planner service's /summarize endpoint
 * expects, so it comes back enriched like a catalog template.
 * Returns null for records that can't be mapped.
 */
export function dbBuildToSummarizeInput(build, labels) {
  const planner = dbBuildToPlannerBuild(build, labels)
  if (!planner) return null
  return {
    id: String(build.id),
    name: build.display_name || 'Untitled Build',
    ...planner,
  }
}

/** Sort options offered by the gallery, in menu order. */
export const TEMPLATE_SORTS = [
  { key: 'badgeScore', label: 'Badge quality' },
  { key: 'legend', label: 'Legend badges' },
  { key: 'hof', label: 'Hall of Fame badges' },
  { key: 'total', label: 'Total badges' },
  { key: 'ovr', label: 'Overall' },
  { key: 'name', label: 'Name (A–Z)' },
]

const byName = (a, b) => a.name.localeCompare(b.name)

/** Comparator for a sort key. Every tier sort falls back to badge score, then name. */
export function templateComparator(sortKey) {
  switch (sortKey) {
    case 'legend':
      return (a, b) => (b.badgeCounts.Legend - a.badgeCounts.Legend) || (b.badgeScore - a.badgeScore) || byName(a, b)
    case 'hof':
      return (a, b) => (b.badgeCounts.HallOfFame - a.badgeCounts.HallOfFame) || (b.badgeScore - a.badgeScore) || byName(a, b)
    case 'total':
      return (a, b) => (b.badgeCounts.total - a.badgeCounts.total) || (b.badgeScore - a.badgeScore) || byName(a, b)
    case 'ovr':
      return (a, b) => (b.ovr - a.ovr) || (b.badgeScore - a.badgeScore) || byName(a, b)
    case 'name':
      return byName
    case 'badgeScore':
    default:
      return (a, b) => (b.badgeScore - a.badgeScore) || byName(a, b)
  }
}
