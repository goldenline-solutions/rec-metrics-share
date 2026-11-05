import { useState, useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import UserMenu from '../components/UserMenu'
import { getMyClaims, createClaim, requestVerification } from '../utils/api'
import './ClaimsPage.css'

function ClaimsPage() {
  const [claims, setClaims] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newClaimName, setNewClaimName] = useState('')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    loadClaims()
  }, [])

  const loadClaims = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await getMyClaims()
      setClaims(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleCreateClaim = async (e) => {
    e.preventDefault()
    if (!newClaimName.trim()) {
      setError('Please enter a display name')
      return
    }

    try {
      setCreating(true)
      setError(null)
      await createClaim(newClaimName.trim())
      setNewClaimName('')
      setShowCreateForm(false)
      await loadClaims()
    } catch (err) {
      setError(err.message)
    } finally {
      setCreating(false)
    }
  }

  const handleRequestVerification = async (claimId) => {
    try {
      await requestVerification(claimId)
      await loadClaims()
    } catch (err) {
      setError(err.message)
    }
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'verified':
        return 'status-verified'
      case 'unverified':
        return 'status-unverified'
      case 'rejected':
        return 'status-rejected'
      case 'revoked':
        return 'status-revoked'
      default:
        return ''
    }
  }

  return (
    <div className="container">
      <div className="page-header">
        <div className="page-header-content">
          <h1>My Username Claims</h1>
          <nav>
            <NavLink to="/" end>Upload</NavLink>
            <NavLink to="/games">Games List</NavLink>
            <NavLink to="/stats">Stats</NavLink>
            <NavLink to="/leaderboard">Leaderboard</NavLink>
          </nav>
        </div>
        <UserMenu />
      </div>

      <div className="claims-page-content">
        {error && (
          <div className="error-message">
            {error}
          </div>
        )}

        <div className="claims-actions">
          <button
            onClick={() => setShowCreateForm(!showCreateForm)}
            className="btn btn-primary"
          >
            {showCreateForm ? 'Cancel' : 'Create New Claim'}
          </button>
        </div>

        {showCreateForm && (
          <div className="create-claim-form">
            <form onSubmit={handleCreateClaim}>
              <div className="form-group">
                <label htmlFor="displayName">Display Name:</label>
                <input
                  type="text"
                  id="displayName"
                  value={newClaimName}
                  onChange={(e) => setNewClaimName(e.target.value)}
                  placeholder="Enter your username"
                  required
                />
              </div>
              <button type="submit" disabled={creating} className="btn btn-primary">
                {creating ? 'Creating...' : 'Create Claim'}
              </button>
            </form>
          </div>
        )}

        {loading ? (
          <div className="loading">Loading claims...</div>
        ) : claims.length === 0 ? (
          <div className="empty-state">
            <p>You don't have any claims yet.</p>
            <p>Create a claim to link your username to your game history.</p>
          </div>
        ) : (
          <div className="claims-list">
            {claims.map((claim) => (
              <div key={claim.id} className={`claim-card ${getStatusColor(claim.status)}`}>
                <div className="claim-header">
                  <h3>{claim.display_name}</h3>
                  <span className={`status-badge ${getStatusColor(claim.status)}`}>
                    {claim.status}
                  </span>
                </div>
                <div className="claim-details">
                  <p><strong>Platform:</strong> {claim.platform || 'N/A'}</p>
                  <p><strong>Canonical Name:</strong> {claim.canonical_name || 'N/A'}</p>
                  <p><strong>Games Linked:</strong> {claim.games_count || 0}</p>
                  <p><strong>Created:</strong> {new Date(claim.created_at).toLocaleDateString()}</p>
                  {claim.verified_at && (
                    <p><strong>Verified:</strong> {new Date(claim.verified_at).toLocaleDateString()}</p>
                  )}
                </div>
                {claim.status === 'unverified' && (
                  <div className="claim-actions">
                    <button
                      onClick={() => handleRequestVerification(claim.id)}
                      className="btn btn-secondary"
                    >
                      Request Verification
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default ClaimsPage

