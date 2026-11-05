// Post-build prerender: emit a static HTML file per route with route-specific
// <head> meta (title, description, canonical, OG, Twitter) baked in.
//
// WHY: the app is a client-rendered SPA served with an index.html SPA fallback.
// Social scrapers (Discord, X, Facebook, Slack) and non-JS crawlers read the
// STATIC HTML that the server returns for a URL — they don't run React. Without
// this, a shared link to /builds/new returns index.html with the homepage's
// meta, so the preview is wrong. Generating dist/builds/new/index.html (etc.)
// means `try_files $uri $uri/ /index.html` serves the right meta per path.
//
// This bakes only the <head>; the <body> stays the empty root shell, so there's
// no risk of freezing a loading/error state and no hydration mismatch — React
// mounts normally for real users.

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const DIST = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist')
const ORIGIN = 'https://rec-metrics.com'
const IMAGE = `${ORIGIN}/og-image.png`

// Keep titles/descriptions in sync with the per-route <Seo> components.
const ROUTES = {
  '/': {
    title: 'RecMetrics — NBA 2K26 Build Planner',
    description: 'Plan your perfect NBA 2K26 build with a live overall, soft caps, badges, takeovers, and animations. Start from 270+ template builds, then track your REC stats and leaderboards.',
  },
  '/builds/new': {
    title: 'NBA 2K26 Build Planner — Live OVR, Badges & Animations | RecMetrics',
    description: 'Build any NBA 2K26 player with a live overall rating, attribute soft caps, badges, takeovers, animations, and cap breakers. Free — no login needed to plan.',
  },
  '/builds/templates': {
    title: 'NBA 2K26 Template Builds — Browse & Customize | RecMetrics',
    description: 'Browse proven NBA 2K26 template builds by position, height, and badge quality. Start from any template and customize it in the build planner.',
  },
  '/builds': {
    title: 'Community NBA 2K26 Builds | RecMetrics',
    description: 'Browse NBA 2K26 builds shared by the RecMetrics community — filter by position, see top attributes, and open any build in the planner.',
  },
  '/leaderboard': {
    title: 'NBA 2K26 REC Leaderboards | RecMetrics',
    description: 'NBA 2K26 REC leaderboards — top players by points, rebounds, assists and more, filterable by position and platform.',
  },
  '/stats': {
    title: 'NBA 2K26 REC Player Stats | RecMetrics',
    description: 'Search NBA 2K26 REC player statistics and role-based performance grades. Find any tracked player and view their game logs.',
  },
}

const esc = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** Replace the value of a tag matched by `pattern` (capturing group 1 = value to swap). */
function replaceTag(html, pattern, value) {
  return html.replace(pattern, (m, p1) => m.replace(p1, esc(value)))
}

function renderRoute(template, path, meta) {
  const canonical = `${ORIGIN}${path === '/' ? '/' : path}`
  let html = template

  html = html.replace(/<title>([\s\S]*?)<\/title>/, `<title>${esc(meta.title)}</title>`)
  html = replaceTag(html, /<meta name="description" content="([\s\S]*?)"\s*\/>/, meta.description)
  html = replaceTag(html, /<link rel="canonical" href="([\s\S]*?)"\s*\/>/, canonical)
  html = replaceTag(html, /<meta property="og:title" content="([\s\S]*?)"\s*\/>/, meta.title)
  html = replaceTag(html, /<meta property="og:description" content="([\s\S]*?)"\s*\/>/, meta.description)
  html = replaceTag(html, /<meta property="og:url" content="([\s\S]*?)"\s*\/>/, canonical)
  html = replaceTag(html, /<meta property="og:image" content="([\s\S]*?)"\s*\/>/, IMAGE)
  html = replaceTag(html, /<meta name="twitter:title" content="([\s\S]*?)"\s*\/>/, meta.title)
  html = replaceTag(html, /<meta name="twitter:description" content="([\s\S]*?)"\s*\/>/, meta.description)
  return html
}

const template = readFileSync(join(DIST, 'index.html'), 'utf-8')
let count = 0
for (const [path, meta] of Object.entries(ROUTES)) {
  const html = renderRoute(template, path, meta)
  const outDir = path === '/' ? DIST : join(DIST, path)
  mkdirSync(outDir, { recursive: true })
  writeFileSync(join(outDir, 'index.html'), html, 'utf-8')
  count++
  console.log(`prerendered ${path} -> ${join(outDir, 'index.html').replace(DIST, 'dist')}`)
}
console.log(`Prerendered ${count} routes.`)
