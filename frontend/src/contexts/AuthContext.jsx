import { createContext, useContext, useState, useEffect } from 'react'
import { Events } from '../utils/analytics'
import { apiUrl } from '../utils/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showPlatformModal, setShowPlatformModal] = useState(false)

  // Fetch current user on mount
  useEffect(() => {
    checkAuth()
  }, [])

  // Check if platform selection is needed
  useEffect(() => {
    if (user && !user.platform) {
      setShowPlatformModal(true)
    } else {
      setShowPlatformModal(false)
    }
  }, [user])

  const checkAuth = async () => {
    try {
      const response = await fetch(apiUrl('/api/me'), {
        credentials: 'include' // Include cookies
      })
      
      if (response.ok) {
        const userData = await response.json()
        setUser(userData)
        // Fire a conversion once per browser session when an authenticated
        // session is confirmed (approximates a sign-in for ad attribution).
        try {
          if (!sessionStorage.getItem('rm_signed_in_tracked')) {
            sessionStorage.setItem('rm_signed_in_tracked', '1')
            Events.signedIn()
          }
        } catch { /* no storage — skip */ }
      } else {
        setUser(null)
      }
    } catch (error) {
      console.error('Auth check failed:', error)
      setUser(null)
    } finally {
      setLoading(false)
    }
  }

  const handlePlatformSelected = (platform) => {
    // Update user object with platform
    setUser(prev => prev ? { ...prev, platform } : null)
    setShowPlatformModal(false)
    // Refresh auth to get updated user
    checkAuth()
  }

  const login = () => {
    // Redirect to backend Discord OAuth endpoint
    window.location.href = apiUrl('/api/auth/discord')
  }

  const logout = async () => {
    try {
      await fetch(apiUrl('/api/auth/logout'), {
        method: 'POST',
        credentials: 'include'
      })
    } catch (error) {
      console.error('Logout failed:', error)
    } finally {
      setUser(null)
      // Optionally redirect to home
      window.location.href = '/'
    }
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, checkAuth, showPlatformModal, handlePlatformSelected }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}

