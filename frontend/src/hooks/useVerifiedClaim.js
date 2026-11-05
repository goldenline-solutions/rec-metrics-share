import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { getMyClaims } from '../utils/api'

export function useVerifiedClaim() {
  const { user, loading: authLoading } = useAuth()
  const [verifiedClaim, setVerifiedClaim] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchVerifiedClaim = async () => {
      if (!user || authLoading) {
        setVerifiedClaim(null)
        setLoading(false)
        return
      }

      setLoading(true)
      try {
        const claims = await getMyClaims()
        
        if (!Array.isArray(claims)) {
          setVerifiedClaim(null)
          return
        }
        
        // Find the claim for user's current platform (prefer verified, but show unverified if that's all they have)
        // If user has no platform, show first verified claim
        const verified = claims.find(claim => {
          if (!claim) {
            return false
          }
          const status = claim.status ? claim.status.toLowerCase() : null
          const hasDisplayName = !!claim.display_name
          const matchesPlatform = !user.platform || claim.platform === user.platform
          // Accept verified or unverified claims that match user's platform (or any if no platform set)
          return (status === 'verified' || status === 'unverified') && hasDisplayName && matchesPlatform
        })
        
        setVerifiedClaim(verified || null)
      } catch (err) {
        console.error('useVerifiedClaim: Failed to load claims:', err)
        setVerifiedClaim(null)
      } finally {
        setLoading(false)
      }
    }

    fetchVerifiedClaim()
  }, [user, authLoading])

  return { verifiedClaim, loading }
}

