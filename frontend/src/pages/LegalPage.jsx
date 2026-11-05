import { useEffect } from 'react'
import PageLayout from '../components/PageLayout'
import './LegalPage.css'

/**
 * Legal page: Privacy Policy and Terms of Service.
 * Linked from the site footer only (no nav spot).
 */
export default function LegalPage() {
  // When visiting /legal#privacy or /legal#terms, scroll to that section after mount
  useEffect(() => {
    const hash = window.location.hash
    if (hash) {
      const el = document.querySelector(hash)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [])

  return (
    <PageLayout title="Legal" className="legal-page">
      <div className="legal-content">
        <section id="privacy" className="legal-section">
          <h2>Privacy Policy</h2>
          <p><strong>Last updated:</strong> February 2025</p>
          <p>
            RecMetrics (“we”) collects only what’s needed to run the service: your Discord identity when you sign in,
            and any data you provide (e.g. usernames, game stats). We use this to show your stats, leaderboards, and
            claims. We don’t sell your data. We may use cookies or similar tech for sign-in and preferences.
          </p>
          <p>
            Data is stored on our servers and may be retained for as long as your account exists or as required by law.
            You can stop using the site at any time; account deletion requests can be sent to the site operators.
          </p>
        </section>

        <section id="terms" className="legal-section">
          <h2>Terms of Service</h2>
          <p><strong>Last updated:</strong> February 2025</p>
          <p>
            By using RecMetrics you agree to use it only for lawful purposes. Don’t upload fake data, abuse other
            users, or try to break the service. We reserve the right to remove content or suspend access if we believe
            these terms are violated.
          </p>
          <p>
            The site and grades/stats are provided “as is.” We’re not liable for decisions you make based on the data.
            We may change these terms or the service with reasonable notice where practical.
          </p>
        </section>
      </div>
    </PageLayout>
  )
}
