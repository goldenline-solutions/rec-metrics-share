// Analytics: GA4 (acquisition/ads) + a first-party event beacon (durable,
// ad-blocker-resistant product data we own).
//
// GA4's automatic page_view is disabled in index.html (send_page_view:false)
// because this is a SPA — we send page_view manually on every route change here,
// otherwise only the first load would ever register.

const GA_ID = 'G-K31T2NG8M0'
const ATTRIBUTION_KEY = 'rm_attribution'
const EVENTS_ENDPOINT = '/api/events'

function gtag(...args) {
  if (typeof window !== 'undefined' && typeof window.gtag === 'function') {
    window.gtag(...args)
  }
}

/**
 * Capture campaign attribution once per session (first-touch). Ad platforms send
 * utm_* params and a click id (gclid); we stash them so every later event can be
 * attributed to the campaign that brought the user in.
 */
export function captureAttribution(search = window.location.search) {
  try {
    if (sessionStorage.getItem(ATTRIBUTION_KEY)) return
    const p = new URLSearchParams(search)
    const keys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid', 'fbclid']
    const attribution = {}
    for (const k of keys) {
      const v = p.get(k)
      if (v) attribution[k] = v
    }
    if (Object.keys(attribution).length) {
      attribution.landing_path = window.location.pathname
      sessionStorage.setItem(ATTRIBUTION_KEY, JSON.stringify(attribution))
    }
  } catch { /* private mode / no storage — attribution is best-effort */ }
}

function getAttribution() {
  try {
    const raw = sessionStorage.getItem(ATTRIBUTION_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}

/** Send a page_view to GA4 and a first-party pageview beacon. Call on route change. */
export function trackPageView(path) {
  gtag('event', 'page_view', { page_path: path, page_location: window.location.href, page_title: document.title })
  sendBeacon('pageview', { path })
}

/**
 * Track a named event (e.g. a conversion) in BOTH GA4 and the first-party log.
 * Keep params free of PII — these are product/marketing signals, not user records.
 */
export function trackEvent(name, params = {}) {
  gtag('event', name, params)
  sendBeacon(name, params)
}

/** Fire-and-forget POST to the first-party event log. Never blocks or throws. */
function sendBeacon(name, params) {
  try {
    const payload = JSON.stringify({
      name,
      path: window.location.pathname,
      params,
      attribution: getAttribution(),
      referrer: document.referrer || null,
      ts: new Date().toISOString(),
    })
    // sendBeacon survives page unloads (e.g. an outbound click) and doesn't block.
    if (navigator.sendBeacon) {
      navigator.sendBeacon(EVENTS_ENDPOINT, new Blob([payload], { type: 'application/json' }))
    } else {
      fetch(EVENTS_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: payload, keepalive: true, credentials: 'include' })
        .catch(() => {})
    }
  } catch { /* analytics must never break the app */ }
}

// Named conversion events — one place so GA4 and the first-party log stay in sync.
export const Events = {
  openedPlanner: (params) => trackEvent('opened_planner', params),
  startedFromTemplate: (params) => trackEvent('started_from_template', params),
  savedBuild: (params) => trackEvent('saved_build', params),
  signedIn: (params) => trackEvent('signed_in', params),
}

export { GA_ID }
