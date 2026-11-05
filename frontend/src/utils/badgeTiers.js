// Badge tier constants, shared by the planner and the template gallery.
//
// Tier color is meaningful in 2K — it's how players read badge strength at a
// glance — so each tier maps to its own Badge variant rather than reusing the
// semantic ones (a Legend badge is the best outcome, not an error).
// Colors live in Badge.css / index.css as --color-tier-*.

/** Tier keys, weakest to strongest — the order the engine returns thresholds in. */
export const TIER_KEYS = ['Bronze', 'Silver', 'Gold', 'HallOfFame', 'Legend']

/** Strongest to weakest, for ranking and for tier summaries on cards. */
export const TIER_KEYS_DESC = ['Legend', 'HallOfFame', 'Gold', 'Silver', 'Bronze']

export const TIER_LABEL = {
  Bronze: 'Bronze',
  Silver: 'Silver',
  Gold: 'Gold',
  HallOfFame: 'HoF',
  Legend: 'Legend',
}

/** Badge component variant per tier -> `.badge-tier-*` in Badge.css. */
export const BADGE_VARIANT = {
  Legend: 'tier-legend',
  HallOfFame: 'tier-hof',
  Gold: 'tier-gold',
  Silver: 'tier-silver',
  Bronze: 'tier-bronze',
}

/** Variant for a tier, falling back to the neutral chip for unknown values. */
export function tierVariant(level) {
  return BADGE_VARIANT[level] || 'default'
}

/** Display label for a tier, falling back to the raw value. */
export function tierLabel(level) {
  return TIER_LABEL[level] || level
}
