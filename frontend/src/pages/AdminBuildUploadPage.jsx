import { useState } from 'react'
import { ingestBuildSheet, hasRole, findUserByUsername } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import Navigation from '../components/Navigation'
import './AdminBuildUploadPage.css'

function AdminBuildUploadPage() {
  const { user } = useAuth()
  const [uploadFile, setUploadFile] = useState(null)
  const [targetUsername, setTargetUsername] = useState('')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [uploadedBuild, setUploadedBuild] = useState(null)
  const [isPublic, setIsPublic] = useState(false)

  // Check if user is admin
  if (!user || !hasRole(user, 'admin')) {
    return (
      <>
        <Navigation />
        <div className="container">
          <div className="page-header">
            <h1>Admin Build Upload</h1>
          </div>
          <div className="error-message">
            <strong>Access Denied:</strong> Admin access required to upload builds.
          </div>
        </div>
      </>
    )
  }

  const handleFileChange = (e) => {
    const file = e.target.files[0]
    if (file) {
      setUploadFile(file)
      setError(null)
      setSuccess(null)
      setUploadedBuild(null)
    }
  }

  const handleUpload = async () => {
    if (!uploadFile) {
      setError('Please select a build sheet image')
      return
    }

    if (!targetUsername || !targetUsername.trim()) {
      setError('Please enter a target username')
      return
    }

    setUploading(true)
    setError(null)
    setSuccess(null)
    setUploadedBuild(null)

    try {
      // First, find the user ID for the target username
      let targetUserId = null
      try {
        const userInfo = await findUserByUsername(targetUsername.trim())
        targetUserId = userInfo.user_id
      } catch (err) {
        // If user not found, we can still create the build but it won't be assigned to anyone
        // For now, we'll show an error - in the future we could create a placeholder user
        setError(`User not found: ${targetUsername}. Please ensure the username has been claimed.`)
        setUploading(false)
        return
      }
      
      // Upload the build with the target user ID
      const result = await ingestBuildSheet(uploadFile, targetUserId, isPublic)
      
      setUploadedBuild(result)
      setSuccess(`Build "${result.display_name}" uploaded successfully and assigned to ${targetUsername}!`)
      setUploadFile(null)
      setTargetUsername('')
      setIsPublic(false)
      
      // Reset file input
      const fileInput = document.getElementById('build-file-input')
      if (fileInput) {
        fileInput.value = ''
      }
    } catch (err) {
      setError(err.message || 'Failed to upload build')
      console.error('Upload error:', err)
    } finally {
      setUploading(false)
    }
  }

  return (
    <>
      <Navigation />
      <div className="container">
        <div className="page-header">
          <h1>Admin Build Upload</h1>
        </div>

        <div className="admin-build-upload-content">
          <div className="card">
            <h2>Upload Build Sheet</h2>
            <p style={{ color: 'var(--color-text-secondary)', marginBottom: '20px' }}>
              Upload a build sheet screenshot and assign it to a username (even if not claimed).
            </p>

            <div className="upload-form">
              <div className="form-group">
                <label htmlFor="target-username">
                  Target Username:
                  <input
                    id="target-username"
                    type="text"
                    value={targetUsername}
                    onChange={(e) => setTargetUsername(e.target.value)}
                    placeholder="Enter username (e.g., PlayerName)"
                    style={{
                      padding: '8px 12px',
                      fontSize: '14px',
                      width: '100%',
                      maxWidth: '400px',
                      marginTop: '5px'
                    }}
                  />
                </label>
                <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '5px' }}>
                  Enter the username to assign this build to. The username will be matched to a user account if it exists.
                </p>
              </div>

            <div className="form-group">
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 500 }}>
                <input
                  type="checkbox"
                  checked={isPublic}
                  onChange={(e) => setIsPublic(e.target.checked)}
                />
                Make this build public
              </label>
              <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '5px' }}>
                Default is private. Private builds are only visible to the owner/admin.
              </p>
            </div>

            <div className="form-group">
              <label htmlFor="build-file-input">
                Build Sheet Image:
                <input
                  id="build-file-input"
                  type="file"
                  accept="image/*"
                  onChange={handleFileChange}
                  style={{
                    padding: '8px',
                    fontSize: '14px',
                    marginTop: '5px'
                  }}
                />
              </label>
              <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '5px' }}>
                Upload a screenshot of the "Attribute Upgrades: Simple View" screen from NBA 2K.
              </p>
            </div>

            {error && (
              <div className="error-message" style={{ marginTop: '15px' }}>
                <strong>Error:</strong> {error}
              </div>
            )}

            {success && (
              <div className="success-message" style={{ marginTop: '15px', color: 'var(--color-positive)' }}>
                <strong>Success:</strong> {success}
              </div>
            )}

            {uploadedBuild && (
              <div className="uploaded-build-info" style={{ marginTop: '20px', padding: '15px', backgroundColor: 'var(--color-surface-2)', borderRadius: '4px' }}>
                <h3>Uploaded Build Details</h3>
                <p><strong>Name:</strong> {uploadedBuild.display_name}</p>
                {uploadedBuild.position && <p><strong>Position:</strong> {uploadedBuild.position}</p>}
                {uploadedBuild.archetype && <p><strong>Archetype:</strong> {uploadedBuild.archetype}</p>}
                {uploadedBuild.overall_current && (
                  <p>
                    <strong>Overall:</strong> {uploadedBuild.overall_current}
                    {uploadedBuild.overall_max && ` / ${uploadedBuild.overall_max} MAX`}
                  </p>
                )}
              </div>
            )}

              <button
                onClick={handleUpload}
                disabled={uploading || !uploadFile || !targetUsername.trim()}
                style={{
                  marginTop: '20px',
                  padding: '10px 20px',
                  fontSize: '16px',
                  backgroundColor: uploading ? 'var(--color-text-secondary)' : 'var(--color-accent)',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: uploading ? 'not-allowed' : 'pointer'
                }}
              >
                {uploading ? 'Uploading...' : 'Upload Build'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

export default AdminBuildUploadPage
