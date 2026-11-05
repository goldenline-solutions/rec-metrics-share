import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { captureAttribution, trackPageView } from '../utils/analytics'

/**
 * Fires a GA4 + first-party page_view on every route change (SPAs don't get
 * these for free), and captures campaign attribution on first load. Renders
 * nothing; must live inside the Router.
 */
export default function AnalyticsListener() {
  const location = useLocation()

  useEffect(() => {
    captureAttribution()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    // Defer a tick so document.title (set by react-helmet) reflects the new route.
    const id = setTimeout(() => trackPageView(location.pathname + location.search), 0)
    return () => clearTimeout(id)
  }, [location.pathname, location.search])

  return null
}
