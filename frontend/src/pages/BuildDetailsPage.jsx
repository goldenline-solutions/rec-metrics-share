import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import PageLayout from '../components/PageLayout'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { apiUrl, getBuild, getBuildUsage, getBuildVotes, voteBuild } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import Seo from '../components/Seo'
import './BuildDetailsPage.css'

function formatBuildName(displayName) {
  if (!displayName) return ''
  const timestampPattern = /\s*-\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?/i
  return displayName.replace(timestampPattern, '').trim()
}

function formatDate(dateString) {
  if (!dateString) return 'N/A'
  try {
    return new Date(dateString).toLocaleString()
  } catch {
    return dateString
  }
}

export default function BuildDetailsPage() {
  const { user } = useAuth()
  const { id } = useParams()
  const [build, setBuild] = useState(null)
  const [usage, setUsage] = useState(null)
  const [votes, setVotes] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [voting, setVoting] = useState(false)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const [buildData, usageData] = await Promise.all([
          getBuild(id),
          getBuildUsage(id)
        ])
        setBuild(buildData)
        setUsage(usageData)
        try {
          const voteData = await getBuildVotes(id)
          setVotes(voteData)
        } catch {
          setVotes(null)
        }
      } catch (err) {
        setError(err.message || 'Failed to load build details')
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [id])

  if (loading) {
    return <PageLayout title="Build Details">Loading build...</PageLayout>
  }

  if (error || !build) {
    return (
      <PageLayout title="Build Details">
        <div className="error-message">
          <strong>Error:</strong> {error || 'Build not found'}
        </div>
      </PageLayout>
    )
  }

  const handleVote = async (nextVote) => {
    if (!user || voting) return
    const currentVote = votes?.user_vote || null
    const voteToSend = currentVote === nextVote ? null : nextVote
    setVoting(true)
    try {
      const result = await voteBuild(id, voteToSend)
      setVotes(result)
    } catch (err) {
      setError(err.message || 'Failed to submit vote')
    } finally {
      setVoting(false)
    }
  }

  return (
    <PageLayout title={formatBuildName(build.display_name)}>
      <Seo
        title={`${formatBuildName(build.display_name)} — NBA 2K26 Build | RecMetrics`}
        description={`${formatBuildName(build.display_name)}: a ${build.position || 'NBA 2K26'} build${build.archetype ? ` (${build.archetype})` : ''}${build.overall_current ? `, ${build.overall_current} OVR` : ''}. View attributes and open it in the planner.`}
      />
      <div className="build-detail-actions">
        <Link to="/builds">
          <Button variant="outline">Back to Builds</Button>
        </Link>
      </div>
      <Card className="build-details-summary">
        <p>
          <strong>Position:</strong> {build.position || 'N/A'} | <strong>Archetype:</strong> {build.archetype || 'N/A'}
        </p>
        <p>
          <strong>Physicals:</strong> HT {build.height || '-'} | WT {build.weight_lbs ? `${build.weight_lbs} lbs` : '-'} | WS {build.wingspan || '-'}
        </p>
        {usage && (
          <p>
            <strong>Usage:</strong> {usage.games_used || 0} game(s) | PPG {usage.averages?.avg_ppg ?? '-'} | RPG {usage.averages?.avg_rpg ?? '-'} | APG {usage.averages?.avg_apg ?? '-'}
          </p>
        )}
        <div className="build-votes-row">
          <button
            type="button"
            className={`vote-btn ${votes?.user_vote === 'up' ? 'active-up' : ''}`}
            onClick={() => handleVote('up')}
            disabled={!user || voting}
          >
            Up {votes?.upvotes ?? 0}
          </button>
          <button
            type="button"
            className={`vote-btn ${votes?.user_vote === 'down' ? 'active-down' : ''}`}
            onClick={() => handleVote('down')}
            disabled={!user || voting}
          >
            Down {votes?.downvotes ?? 0}
          </button>
          {!user && <span className="vote-login-hint">Log in to vote</span>}
        </div>
      </Card>

      {build.screenshot_url && (
        <Card>
          <h3>Build Screenshot</h3>
          <img
            src={apiUrl(build.screenshot_url)}
            alt="Build screenshot"
            className="build-details-image"
          />
        </Card>
      )}

      <Card>
        <h3>Full Attributes</h3>
        <div className="build-attrs-grid">
          {build.attributes_by_category && Object.entries(build.attributes_by_category).map(([category, attrs]) => (
            <div key={category} className="build-attr-section">
              <h4>{category}</h4>
              {attrs.map((attr) => (
                <div key={`${category}-${attr.name}`} className="build-attr-row">
                  <span>{attr.name}</span>
                  <strong>
                    {attr.current}{attr.max ? ` / ${attr.max}` : ''}
                  </strong>
                </div>
              ))}
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <h3>In-Game Stat Breakdown</h3>
        {!usage || !usage.games || usage.games.length === 0 ? (
          <p>No game stats linked to this build yet.</p>
        ) : (
          <div className="build-games-table-wrap">
            <table className="build-games-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Game</th>
                  <th>POS</th>
                  <th>PTS</th>
                  <th>REB</th>
                  <th>AST</th>
                  <th>STL</th>
                  <th>BLK</th>
                  <th>TOV</th>
                  <th>FG</th>
                  <th>3PT</th>
                  <th>FT</th>
                  <th>Grade</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {usage.games.map((game) => (
                  <tr key={`${game.game_id}-${game.created_at}`}>
                    <td>{formatDate(game.created_at)}</td>
                    <td>
                      <Link to={`/games/${game.game_id}`}>
                        {game.team_score}-{game.opponent_score}
                      </Link>
                    </td>
                    <td>{game.position || '-'}</td>
                    <td>{game.stats?.pts ?? 0}</td>
                    <td>{game.stats?.reb ?? 0}</td>
                    <td>{game.stats?.ast ?? 0}</td>
                    <td>{game.stats?.stl ?? 0}</td>
                    <td>{game.stats?.blk ?? 0}</td>
                    <td>{game.stats?.tov ?? 0}</td>
                    <td>{game.stats?.fgm ?? 0}/{game.stats?.fga ?? 0}</td>
                    <td>{game.stats?.tpm ?? 0}/{game.stats?.tpa ?? 0}</td>
                    <td>{game.stats?.ftm ?? 0}/{game.stats?.fta ?? 0}</td>
                    <td>{game.stats?.grade || '-'}</td>
                    <td>
                      <Link to={`/games/${game.game_id}`} className="view-game-btn">
                        View Game
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </PageLayout>
  )
}
