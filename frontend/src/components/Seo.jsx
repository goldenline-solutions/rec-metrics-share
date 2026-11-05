import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

// Canonical production origin. Every page's canonical + OG URL is built from this
// so social scrapers and search engines converge on one host (rec-metrics.com),
// regardless of which domain actually served the request.
const SITE_ORIGIN = 'https://rec-metrics.com'
const DEFAULT_IMAGE = `${SITE_ORIGIN}/og-image.png`

// Head tags are managed imperatively rather than via react-helmet-async: that
// library silently no-ops under this Vite build (renders zero tags), whereas a
// direct DOM sync is bulletproof and updates the exact tags index.html already
// ships — so tags are replaced in place, never duplicated. The static defaults
// in index.html + the prerender step cover crawlers/scrapers that don't run JS;
// this keeps the live tab title and meta correct as users navigate the SPA.

function upsertMeta(attr, key, content) {
  if (content == null) return
  let el = document.head.querySelector(`meta[${attr}="${key}"]`)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, key)
    document.head.appendChild(el)
  }
  el.setAttribute('content', content)
}

function upsertLink(rel, href) {
  let el = document.head.querySelector(`link[rel="${rel}"]`)
  if (!el) {
    el = document.createElement('link')
    el.setAttribute('rel', rel)
    document.head.appendChild(el)
  }
  el.setAttribute('href', href)
}

/**
 * Per-route SEO tags. Sits inside any page (all pages render within the Router)
 * and overrides the static defaults in index.html for that route.
 *
 * @param {string} title - full <title> for the page
 * @param {string} description - meta description + OG/Twitter description
 * @param {string} [path] - canonical path override; defaults to the current location
 * @param {string} [image] - absolute OG image URL; defaults to the site card
 * @param {boolean} [noindex] - set on pages that shouldn't be indexed
 */
export default function Seo({ title, description, path, image = DEFAULT_IMAGE, noindex = false }) {
  const location = useLocation()
  const canonical = `${SITE_ORIGIN}${path ?? location.pathname}`

  useEffect(() => {
    if (title) {
      document.title = title
      upsertMeta('property', 'og:title', title)
      upsertMeta('name', 'twitter:title', title)
    }
    if (description) {
      upsertMeta('name', 'description', description)
      upsertMeta('property', 'og:description', description)
      upsertMeta('name', 'twitter:description', description)
    }
    upsertLink('canonical', canonical)
    upsertMeta('property', 'og:url', canonical)
    upsertMeta('property', 'og:image', image)
    upsertMeta('name', 'twitter:image', image)

    const robots = document.head.querySelector('meta[name="robots"]')
    if (noindex) {
      upsertMeta('name', 'robots', 'noindex, follow')
    } else if (robots && robots.getAttribute('content')?.includes('noindex')) {
      // A previous noindex page left this behind; clear it for indexable routes.
      robots.remove()
    }
  }, [title, description, canonical, image, noindex])

  return null
}
