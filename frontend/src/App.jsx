import { useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { GameVersionProvider } from './contexts/GameVersionContext'
import LandingPage from './pages/LandingPage'
import UploadPage from './pages/UploadPage'
import GamesListPage from './pages/GamesListPage'
import GameDetailsPage from './pages/GameDetailsPage'
import PlayerStatsPage from './pages/PlayerStatsPage'
import PlayerProfilePage from './pages/PlayerProfilePage'
import LeaderboardPage from './pages/LeaderboardPage'
import LoginPage from './pages/LoginPage'
import ClaimsPage from './pages/ClaimsPage'
import UnresolvedPage from './pages/UnresolvedPage'
import AdminBuildUploadPage from './pages/AdminBuildUploadPage'
import BuildsPage from './pages/BuildsPage'
import BuildDetailsPage from './pages/BuildDetailsPage'
import TemplatesPage from './pages/TemplatesPage'
import LegalPage from './pages/LegalPage'
import ContactPage from './pages/ContactPage'
import ProtectedRoute from './components/ProtectedRoute'
import LeaguePage from './pages/LeaguePage'
import LeaguePlayerPage from './pages/LeaguePlayerPage'
import PlatformSelectionModal from './components/PlatformSelectionModal'
import CookieConsent from './components/CookieConsent'
import AnalyticsListener from './components/AnalyticsListener'
import { apiUrl } from './utils/api'
import './App.css'

// Conditionally import AnalyticsPage only if enabled
// Import is conditional at build time via Vite's environment variable replacement
import AnalyticsPage from './pages/AnalyticsPage'

function AppContent() {
  const { user, showPlatformModal, handlePlatformSelected } = useAuth()
  const enableAnalytics = import.meta.env.VITE_ENABLE_ANALYTICS === 'true'
  
  return (
    <>
      {showPlatformModal && (
        <PlatformSelectionModal
          onPlatformSelected={handlePlatformSelected}
          canSkip={false}
        />
      )}
      <CookieConsent />
      <Router>
        <AnalyticsListener />
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/games" element={<GamesListPage />} />
          <Route path="/games/:id" element={<GameDetailsPage />} />
          <Route path="/stats" element={<PlayerStatsPage />} />
          <Route path="/players/:username" element={<PlayerProfilePage />} />
          <Route path="/leaderboard" element={<LeaderboardPage />} />
          <Route path="/builds" element={<BuildsPage />} />
          <Route path="/builds/templates" element={<TemplatesPage />} />
          <Route path="/builds/:id" element={<BuildDetailsPage />} />
          {/* Not wrapped in ProtectedRoute on purpose: that redirects signed-out
              visitors to "/" with no explanation. LeaguePage shows its own
              sign-in prompt, and the API gates the data regardless. */}
          <Route path="/league" element={<LeaguePage />} />
          <Route path="/league/player/:name" element={<LeaguePlayerPage />} />
          <Route path="/legal" element={<LegalPage />} />
          <Route path="/contact" element={<ContactPage />} />
          <Route 
            path="/profile/claims" 
            element={
              <ProtectedRoute>
                <ClaimsPage />
              </ProtectedRoute>
            } 
          />
          <Route 
            path="/profile/unresolved" 
            element={
              <ProtectedRoute>
                <UnresolvedPage />
              </ProtectedRoute>
            } 
          />
          {enableAnalytics && (
            <Route 
              path="/analytics" 
              element={
                <ProtectedRoute>
                  <AnalyticsPage />
                </ProtectedRoute>
              } 
            />
          )}
          <Route 
            path="/admin/builds" 
            element={
              <ProtectedRoute>
                <AdminBuildUploadPage />
              </ProtectedRoute>
            } 
          />
        </Routes>
      </Router>
    </>
  )
}

function App() {
  // Handle GitHub Pages routing (redirect from 404.html)
  useEffect(() => {
    const path = window.location.pathname
    if (path.includes('/?/')) {
      const newPath = path.split('/?/')[1].replace(/~and~/g, '&')
      window.history.replaceState({}, '', newPath)
    }
  }, [])
  
  return (
    <AuthProvider>
      <GameVersionProvider>
        <AppContent />
      </GameVersionProvider>
    </AuthProvider>
  )
}

export default App

