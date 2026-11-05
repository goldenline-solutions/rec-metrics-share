import { useState, useEffect } from 'react'
import Button from './ui/Button'
import './CookieConsent.css'

const CONSENT_KEY = 'recmetrics_cookie_consent'

/**
 * Cookie consent banner: show once on first load, hide after user accepts.
 * We use cookies for sign-in (session) and localStorage for cache; this records consent.
 */
export default function CookieConsent() {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const accepted = localStorage.getItem(CONSENT_KEY)
    if (accepted !== 'accepted') {
      setVisible(true)
    }
  }, [])

  function handleAccept() {
    localStorage.setItem(CONSENT_KEY, 'accepted')
    setVisible(false)
  }

  if (!visible) return null

  return (
    <div className="cookie-consent" role="dialog" aria-label="Cookie consent">
      <p className="cookie-consent-text">
        We use cookies for sign-in and to remember your preferences.{' '}
        <a href="/legal#privacy">Privacy policy</a>
      </p>
      <Button variant="primary" size="sm" onClick={handleAccept}>
        Accept
      </Button>
    </div>
  )
}
