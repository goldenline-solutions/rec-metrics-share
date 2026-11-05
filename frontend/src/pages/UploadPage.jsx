import { useState } from 'react'
import UploadDropzone from '../components/UploadDropzone'
import BoxScoreSummary from '../components/BoxScoreSummary'
import JsonViewer from '../components/JsonViewer'
import PlatformSelectionModal from '../components/PlatformSelectionModal'
import PageLayout from '../components/PageLayout'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { ingestScreenshot, apiUrl } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import { useVerifiedClaim } from '../hooks/useVerifiedClaim'
import './UploadPage.css'

function UploadPage() {
  const { user, showPlatformModal, handlePlatformSelected } = useAuth()
  const { verifiedClaim, loading: claimsLoading } = useVerifiedClaim()
  const [selectedFile, setSelectedFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const handleFileSelect = (file) => {
    setSelectedFile(file)
    setResult(null)
    setError(null)
  }

  const handleIngest = async () => {
    if (!selectedFile) {
      setError('Please select a file first')
      return
    }

    if (!user) {
      setError('Please log in to upload games')
      return
    }

    if (!user.platform) {
      setError('Please select your platform first')
      return
    }

    setLoading(true)
    setProgress('Uploading screenshot...')
    setError(null)
    setResult(null)

    try {
      const response = await ingestScreenshot(selectedFile)
      
      setProgress('Screenshot ingested successfully!')
      setResult(response)
    } catch (err) {
      setError(err.message || 'Failed to ingest screenshot')
      setProgress('')
    } finally {
      setLoading(false)
    }
  }

  // Show login prompt if not authenticated
  if (!user) {
    return (
      <PageLayout title="Upload Box Score Screenshot">
        <div className="upload-page-content">
          <Card style={{ textAlign: 'center', padding: 'var(--spacing-xl)' }}>
            <h2>Login Required</h2>
            <p>You must be logged in through Discord to upload games.</p>
            <p style={{ marginTop: 'var(--spacing-lg)' }}>
              <Button onClick={() => window.location.href = apiUrl('/api/auth/discord')} style={{
                backgroundColor: '#5865F2'
              }}>
                Login with Discord
              </Button>
            </p>
          </Card>
        </div>
      </PageLayout>
    )
  }

  return (
    <PageLayout title="Upload Box Score Screenshot">
      <div className="upload-page-content">
        <Card className="upload-section">
          <p className="upload-disclaimer">
            Please upload <strong>clean in-game screenshots</strong> (e.g. from your console or PC) when possible. Photos taken of your screen with a phone are harder to read and may not process correctly.
          </p>
          <UploadDropzone 
            onFileSelect={handleFileSelect}
            disabled={loading}
          />
          
          <div className="upload-actions">
            <Button 
              onClick={handleIngest}
              disabled={!selectedFile || loading}
            >
              {loading ? 'Processing...' : 'Ingest Screenshot'}
            </Button>
          </div>

          {loading && progress && (
            <div className="loading">
              <p>{progress}</p>
            </div>
          )}

          {error && (
            <div className="error-message">
              <strong>Error:</strong> {error}
            </div>
          )}

          {result && result.warnings && result.warnings.length > 0 && (
            <div className="warning-message">
              <strong>Warnings:</strong>
              <ul>
                {result.warnings.map((warning, idx) => (
                  <li key={idx}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        {result && (
          <div className="results-section">
            <div className="success-message">
              Screenshot ingested successfully! {result.stored ? 'New game stored.' : 'Game already exists.'}
            </div>
            {result.platform_from_screenshot != null && (
              <div className="platform-feedback" style={{ marginTop: 8, fontSize: 14, color: 'var(--color-text-secondary)' }}>
                <strong>Platform from screenshot:</strong>{' '}
                {result.platform_from_screenshot === 'Console'
                  ? 'Console (controller icons detected)'
                  : result.platform_from_screenshot === 'PC'
                    ? 'PC (no controller icons detected)'
                    : result.platform_from_screenshot || '(not reported)'}
              </div>
            )}
            {result.platform_from_screenshot == null && result.stored && (
              <div className="platform-feedback" style={{ marginTop: 8, fontSize: 14, color: 'var(--color-text-secondary)' }}>
                <strong>Platform from screenshot:</strong> (not reported)
              </div>
            )}

            {result.payload && (
              <>
                <BoxScoreSummary payload={result.payload} />
                
                <JsonViewer 
                  data={result.payload} 
                  title="Extracted JSON Data"
                />
              </>
            )}
          </div>
        )}
      </div>
    </PageLayout>
  )
}

export default UploadPage

