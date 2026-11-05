import SectionTabs from './SectionTabs'

/**
 * BuilderTabs component - the tab bar shared by every page in the Builder
 * section (/builds, /builds/templates, /builds/new).
 *
 * These three used to be three separate top-level nav entries. They are one
 * "Builder" entry now, with the views exposed as tabs here. Defined in one
 * place so the three pages cannot drift apart.
 *
 * Planner is first so it's the section's default landing tab (the "Builder"
 * nav entry points here too). `end` on the Builds tab stops it matching
 * /builds/templates and /builds/new.
 */
const BUILDER_TABS = [
  { to: '/builds/new', label: 'Planner' },
  { to: '/builds/templates', label: 'Templates' },
  { to: '/builds', label: 'Builds', end: true },
]

export default function BuilderTabs() {
  return <SectionTabs tabs={BUILDER_TABS} ariaLabel="Builder" />
}
