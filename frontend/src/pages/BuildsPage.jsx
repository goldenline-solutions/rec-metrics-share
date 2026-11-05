import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import PageLayout from '../components/PageLayout'
import BuilderTabs from '../components/BuilderTabs'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import { getPublicBuilds, voteBuild } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import Seo from '../components/Seo'
import './BuildsPage.css'

const PER_PAGE = 24

function formatBuildName(displayName) {
  if (!displayName) return ''
  const timestampPattern = /\s*-\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?/i
  return displayName.replace(timestampPattern, '').trim()
}

export default function BuildsPage() {
  const { user } = useAuth()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [builds, setBuilds] = useState([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(0)
  const [total, setTotal] = useState(0)
  const [positionFilter, setPositionFilter] = useState('all')
  const [votingById, setVotingById] = useState({})

  useEffect(() => {
    const loadBuilds = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getPublicBuilds(page, PER_PAGE)
        setBuilds(data.builds || [])
        setTotal(data.total || 0)
        setTotalPages(data.total_pages || 0)
      } catch (err) {
        setError(err.message || 'Failed to load builds')
      } finally {
        setLoading(false)
      }
    }

    loadBuilds()
  }, [page])

  if (loading) {
    return <PageLayout title="Builder">
      <BuilderTabs />Loading builds...</PageLayout>
  }

  if (error) {
    return (
      <PageLayout title="Builder">
      <BuilderTabs />
        <div className="error-message">
          <strong>Error:</strong> {error}
        </div>
      </PageLayout>
    )
  }

  const filteredBuilds = builds.filter((build) => {
    if (positionFilter === 'all') return true
    return (build.position || '').toUpperCase() === positionFilter
  })

  const handleVote = async (event, build, nextVote) => {
    event.preventDefault()
    event.stopPropagation()
    if (!user) return
    if (votingById[build.id]) return

    const currentVote = build.votes?.user_vote || null
    const voteToSend = currentVote === nextVote ? null : nextVote

    setVotingById(prev => ({ ...prev, [build.id]: true }))
    try {
      const voteSummary = await voteBuild(build.id, voteToSend)
      setBuilds(prev => prev.map(b => (
        b.id === build.id
          ? { ...b, votes: voteSummary }
          : b
      )))
    } catch (err) {
      setError(err.message || 'Failed to submit vote')
    } finally {
      setVotingById(prev => ({ ...prev, [build.id]: false }))
    }
  }

  return (
    <PageLayout title="Builder">
      <Seo
        title="Community NBA 2K26 Builds | RecMetrics"
        description="Browse NBA 2K26 builds shared by the RecMetrics community — filter by position, see top attributes, and open any build in the planner."
        path="/builds"
      />
      <BuilderTabs />
      {builds.length === 0 ? (
        <EmptyState title="No builds yet" message="No public builds are available right now." />
      ) : (
        <>
          <Card className="builds-controls">
            <div className="builds-controls-row">
              <label htmlFor="build-position-filter">Position:</label>
              <select
                id="build-position-filter"
                value={positionFilter}
                onChange={(e) => setPositionFilter(e.target.value)}
              >
                <option value="all">All</option>
                <option value="PG">PG</option>
                <option value="SG">SG</option>
                <option value="SF">SF</option>
                <option value="PF">PF</option>
                <option value="C">C</option>
              </select>
            </div>
          </Card>
          <div className="builds-grid">
            {filteredBuilds.map((build) => (
              <Link key={build.id} to={`/builds/${build.id}`} className="build-card-link">
                <Card className="build-feed-card">
                  <div className="build-feed-header">
                    <h3>{formatBuildName(build.display_name)}</h3>
                    <span className="build-owner">@{build.owner_display_name || 'Unknown'}</span>
                  </div>
                  <p className="build-feed-meta">
                    {build.position || 'N/A'} | {build.archetype || 'No archetype'}
                  </p>
                  <p className="build-feed-meta">
                    HT {build.height || '-'} | WT {build.weight_lbs ? `${build.weight_lbs} lbs` : '-'} | WS {build.wingspan || '-'}
                  </p>
                  <div className="build-top-attrs">
                    {(build.top_attributes || []).map((attr) => (
                      <span key={`${build.id}-${attr.name}`} className="attr-chip">
                        {attr.name}: {attr.current}
                      </span>
                    ))}
                  </div>
                  <div className="build-feed-usage">
                    {build.usage_stats?.games_used > 0 ? (
                      <>
                        <strong>{build.usage_stats.games_used}</strong> game{build.usage_stats.games_used !== 1 ? 's' : ''} |
                        {' '}PPG {build.usage_stats.avg_ppg} | RPG {build.usage_stats.avg_rpg} | APG {build.usage_stats.avg_apg}
                      </>
                    ) : (
                      <span>No tracked games yet</span>
                    )}
                  </div>
                  <div className="build-votes-row">
                    <button
                      type="button"
                      className={`vote-btn ${build.votes?.user_vote === 'up' ? 'active-up' : ''}`}
                      onClick={(e) => handleVote(e, build, 'up')}
                      disabled={!user || votingById[build.id]}
                      title={user ? 'Thumbs up' : 'Log in to vote'}
                    >
                      Up {build.votes?.upvotes ?? 0}
                    </button>
                    <button
                      type="button"
                      className={`vote-btn ${build.votes?.user_vote === 'down' ? 'active-down' : ''}`}
                      onClick={(e) => handleVote(e, build, 'down')}
                      disabled={!user || votingById[build.id]}
                      title={user ? 'Thumbs down' : 'Log in to vote'}
                    >
                      Down {build.votes?.downvotes ?? 0}
                    </button>
                    {!user && <span className="vote-login-hint">Log in to vote</span>}
                  </div>
                </Card>
              </Link>
            ))}
          </div>
          {totalPages > 1 && (
            <div className="builds-pagination">
              <Button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
                Previous
              </Button>
              <span>
                Page {page} of {totalPages} ({total} total)
              </span>
              <Button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </PageLayout>
  )
}
