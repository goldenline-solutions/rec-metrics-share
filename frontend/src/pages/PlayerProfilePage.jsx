import { useState, useEffect } from 'react'
import { useParams, NavLink, Link } from 'react-router-dom'
import { getPlayerProfile, searchPlayer, createClaim, getMyClaims, getBuilds, ingestBuildSheet, deleteBuild, getBuild, apiUrl, hasRole, getBuildsByUsername, assignBuildToGamePlayer, getPlayerChemistry} from '../utils/api'
import GameVersionSwitch from '../components/GameVersionSwitch'
import { useGameVersion } from '../contexts/GameVersionContext'
import { useAuth } from '../contexts/AuthContext'
import LineChart from '../components/LineChart'
import ShareableStatCard from '../components/ShareableStatCard'
import UserMenu from '../components/UserMenu'
import Navigation from '../components/Navigation'
import Footer from '../components/Footer'
import { useVerifiedClaim } from '../hooks/useVerifiedClaim'
import Seo from '../components/Seo'
import './PlayerProfilePage.css'

// Helper function to remove timestamp from build display name
const formatBuildName = (displayName) => {
  if (!displayName) return ''
  // Remove timestamp pattern: " - YYYY-MM-DDTHH:MM:SSZ" or similar ISO date formats
  const timestampPattern = /\s*-\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?/i
  return displayName.replace(timestampPattern, '').trim()
}

function PlayerProfilePage() {
  const { username } = useParams()
  const { user } = useAuth()
  const { verifiedClaim } = useVerifiedClaim()
  const { gameVersion } = useGameVersion()
  const [activeTab, setActiveTab] = useState('insights')
  const [profile, setProfile] = useState(null)
  const [playerStats, setPlayerStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [statsLoading, setStatsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [userClaims, setUserClaims] = useState([])
  const [claiming, setClaiming] = useState(false)
  const [claimError, setClaimError] = useState(null)
  const [claimSuccess, setClaimSuccess] = useState(false)
  const [builds, setBuilds] = useState([])
  const [buildsLoading, setBuildsLoading] = useState(false)
  const [showAddBuildModal, setShowAddBuildModal] = useState(false)
  const [showBuildDetailModal, setShowBuildDetailModal] = useState(null)
  const [uploadingBuild, setUploadingBuild] = useState(false)
  const [buildError, setBuildError] = useState(null)
  const [newBuildIsPublic, setNewBuildIsPublic] = useState(false)
  const [gamesFilterBy, setGamesFilterBy] = useState('all') // 'all', 'PG', 'SG', 'SF', 'PF', 'C'
  const [platformFilter, setPlatformFilter] = useState('ALL') // 'ALL', 'PC', 'Console'
  const [gamesBuilds, setGamesBuilds] = useState([]) // Builds for games dropdown
  const [assigningBuild, setAssigningBuild] = useState({}) // Track which games are being assigned builds
  const [gamesPage, setGamesPage] = useState(1)
  const GAMES_PER_PAGE = 25

  // Squad chemistry (teammates / rivals), lazy-loaded when the tab opens.
  const [chemistry, setChemistry] = useState(null)
  const [chemistryLoading, setChemistryLoading] = useState(false)
  const [chemistryError, setChemistryError] = useState(null)

  useEffect(() => {
    if (activeTab !== 'squad' || !username) return
    let cancelled = false
    setChemistryLoading(true)
    setChemistryError(null)
    getPlayerChemistry(username, 20)
      .then((data) => { if (!cancelled) setChemistry(data) })
      .catch((e) => { if (!cancelled) setChemistryError(e.message || 'Failed to load chemistry') })
      .finally(() => { if (!cancelled) setChemistryLoading(false) })
    return () => { cancelled = true }
  }, [activeTab, username])

  // Reset games page when username, platform filter or 2K title changes
  useEffect(() => {
    setGamesPage(1)
  }, [username, platformFilter, gameVersion])

  useEffect(() => {
    const fetchProfile = async () => {
      if (!username) {
        setError('Username is required')
        setLoading(false)
        return
      }

      setLoading(true)
      setError(null)

      try {
        const data = await getPlayerProfile(username, gameVersion)
        setProfile(data)
      } catch (err) {
        setError(err.message || 'Failed to load player profile')
        setProfile(null)
      } finally {
        setLoading(false)
      }
    }

    fetchProfile()
  }, [username, gameVersion])

  // Load user claims if logged in
  useEffect(() => {
    const loadClaims = async () => {
      if (user) {
        try {
          const claims = await getMyClaims()
          setUserClaims(claims)
        } catch (err) {
          console.error('Failed to load claims:', err)
        }
      } else {
        setUserClaims([])
      }
    }

    loadClaims()
  }, [user, username])

  useEffect(() => {
    const fetchPlayerStats = async () => {
      if (!username || activeTab !== 'stats' && activeTab !== 'games') {
        return
      }

      setStatsLoading(true)
      try {
        const page = activeTab === 'games' ? gamesPage : 1
        const data = await searchPlayer(username, platformFilter, page, GAMES_PER_PAGE, gameVersion)
        setPlayerStats(data)
      } catch (err) {
        console.error('Failed to load player stats:', err)
      } finally {
        setStatsLoading(false)
      }
    }

    fetchPlayerStats()
  }, [username, activeTab, platformFilter, gamesPage, gameVersion])

  // Load builds when builds tab is active
  useEffect(() => {
    const loadBuilds = async () => {
      if (activeTab !== 'builds') {
        return
      }

      if (builds.length > 0) {
        return // Already loaded
      }

      setBuildsLoading(true)
      try {
        // If logged in and viewing own profile, use getBuilds()
        // Otherwise, use getBuildsByUsername() for public access
        if (user && verifiedClaim && verifiedClaim.display_name?.toLowerCase() === username?.toLowerCase()) {
          const data = await getBuilds()
          setBuilds(data)
        } else {
          // Public access - get builds by username
          const data = await getBuildsByUsername(username)
          setBuilds(data)
        }
      } catch (err) {
        console.error('Failed to load builds:', err)
        setBuildError(err.message)
      } finally {
        setBuildsLoading(false)
      }
    }

    loadBuilds()
  }, [username, activeTab, builds.length, user, verifiedClaim])

  // Load builds for games dropdown when games tab is active
  useEffect(() => {
    const loadGamesBuilds = async () => {
      if (activeTab !== 'games' || !user || !verifiedClaim) {
        return
      }

      // Only load if viewing own profile
      if (verifiedClaim.display_name?.toLowerCase() !== username?.toLowerCase()) {
        return
      }

      if (gamesBuilds.length > 0) {
        return // Already loaded
      }

      try {
        const data = await getBuilds()
        // Filter out builds where display_name matches the player's username (after formatting)
        const normalizedUsername = username?.toLowerCase().trim()
        const filteredBuilds = data.filter(build => {
          const normalizedBuildName = formatBuildName(build.display_name).toLowerCase().trim()
          return normalizedBuildName !== normalizedUsername
        })
        setGamesBuilds(filteredBuilds)
      } catch (err) {
        console.error('Failed to load builds for games:', err)
      }
    }

    loadGamesBuilds()
  }, [username, activeTab, gamesBuilds.length, user, verifiedClaim])


  // Handle build assignment for games
  const handleGameBuildChange = async (gameId, gamePlayerRowId, buildId) => {
    if (!gameId || !gamePlayerRowId) return

    setAssigningBuild(prev => ({ ...prev, [gamePlayerRowId]: true }))
    try {
      await assignBuildToGamePlayer(gameId, gamePlayerRowId, buildId)
      // Reload player stats to show updated build assignment (keep current page)
      const data = await searchPlayer(username, platformFilter, gamesPage, GAMES_PER_PAGE, gameVersion)
      setPlayerStats(data)
    } catch (err) {
      console.error('Failed to assign build:', err)
      alert('Failed to assign build: ' + (err.message || 'Unknown error'))
    } finally {
      setAssigningBuild(prev => ({ ...prev, [gamePlayerRowId]: false }))
    }
  }

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A'
    try {
      const date = new Date(dateString)
      return date.toLocaleString()
    } catch {
      return dateString
    }
  }

  // Filter games by position
  const filterGamesByPosition = (games, filterPosition) => {
    if (!games || filterPosition === 'all') {
      return games
    }
    return games.filter(game => game.position === filterPosition)
  }

  // Filter games by platform (games already filtered by backend, but this is for display)
  const filterGamesByPlatform = (games, filterPlatform) => {
    if (!games || filterPlatform === 'ALL') {
      return games
    }
    return games.filter(game => game.platform === filterPlatform)
  }

  const handleClaimUsername = async () => {
    if (!user) {
      setClaimError('Please log in to claim a username')
      return
    }

    if (!username) {
      setClaimError('No username to claim')
      return
    }

    // Show confirmation dialog
    const confirmed = window.confirm(
      `⚠️ IMPORTANT: Claiming Username\n\n` +
      `You are about to claim the username "${username}".\n\n` +
      `This action is PERMANENT and CANNOT be undone.\n` +
      `You can only claim ONE username per account.\n\n` +
      `Once claimed, all your historical games will be linked to this username.\n\n` +
      `Are you absolutely sure you want to proceed?`
    )

    if (!confirmed) {
      return // User cancelled
    }

    try {
      setClaiming(true)
      setClaimError(null)
      setClaimSuccess(false)
      
      await createClaim(username)
      setClaimSuccess(true)
      
      // Reload claims
      const claims = await getMyClaims()
      setUserClaims(claims)
    } catch (err) {
      setClaimError(err.message || 'Failed to create claim')
    } finally {
      setClaiming(false)
    }
  }

  // Check if user already has any verified claim (only one allowed total)
  const hasAnyVerifiedClaim = () => {
    if (!user || !userClaims.length) return false
    return userClaims.some(claim => claim.status === 'verified')
  }
  
  // Check if user has a claim for this player (on any platform)
  const hasClaimForPlayer = () => {
    if (!user || !userClaims.length || !username) return false
    const normalizedUsername = username.toLowerCase().trim()
    return userClaims.some(claim => 
      (claim.normalized_name === normalizedUsername || 
       claim.display_name.toLowerCase().trim() === normalizedUsername) &&
      claim.status === 'verified'
    )
  }

  const getClaimForPlayer = () => {
    if (!user || !userClaims.length || !username) return null
    const normalizedUsername = username.toLowerCase().trim()
    return userClaims.find(claim => 
      claim.normalized_name === normalizedUsername || 
      claim.display_name.toLowerCase().trim() === normalizedUsername
    )
  }

  if (loading) {
    return (
      <div className="player-profile-page">
        <Navigation />
        <div className="container">
          <div className="page-header">
            <h1>Player Profile</h1>
          </div>
          <div className="player-profile-content">
            <div className="card">
              <p>Loading profile...</p>
            </div>
          </div>
        </div>
        <Footer />
      </div>
    )
  }

  if (error) {
    return (
      <div className="player-profile-page">
        <Navigation />
        <div className="container">
          <div className="page-header">
            <h1>Player Profile</h1>
          </div>
          <div className="player-profile-content">
            <div className="card error-card">
              <h2>Error</h2>
              <p>{error}</p>
            </div>
          </div>
        </div>
        <Footer />
      </div>
    )
  }

  if (!profile || profile.error) {
    return (
      <div className="player-profile-page">
        <Navigation />
        <div className="container">
          <div className="page-header">
            <h1>Player Profile</h1>
          </div>
          <div className="player-profile-content">
            <div className="card">
              <h2>Player Not Found</h2>
              <p>No profile found for {username}</p>
            </div>
          </div>
        </div>
        <Footer />
      </div>
    )
  }

  const { summary, recentTrends, insights, shareCard } = profile

  return (
    <div className="player-profile-page">
      <Seo
        title={`${profile.username} — NBA 2K26 REC Stats | RecMetrics`}
        description={`NBA 2K26 REC stats and performance grades for ${profile.username}${summary?.gamesPlayed ? ` across ${summary.gamesPlayed} tracked games` : ''}.`}
      />
      <Navigation />
      <div className="container">
        <div className="page-header">
          <h1>Player Profile</h1>
        </div>

        <div className="player-profile-content">
          {/* Header */}
          <div className="card profile-header">
            <h2>{profile.username}</h2>
            <p className="games-played">{summary.gamesPlayed} {gameVersion} games played</p>
            <GameVersionSwitch className="profile-version-switch" />
          
            {/* Claim Section - Only show if user is logged in and doesn't have a claim */}
            {user && !hasAnyVerifiedClaim() && (
              <div className="claim-section">
                {hasClaimForPlayer() ? (
                  <div className="claim-status">
                    <span className="claim-badge claim-owned">
                      ✓ You own this username
                    </span>
                    {(() => {
                      const claim = getClaimForPlayer()
                      return claim && (
                        <div className="claim-details">
                          <p className="claim-verified">Verified and linked to your account on {claim.platform || 'your platform'}</p>
                          {claim.games_count > 0 && (
                            <p><strong>Games Linked:</strong> {claim.games_count}</p>
                          )}
                          {claim.platform && (
                            <p><strong>Platform:</strong> {claim.platform}</p>
                          )}
                        </div>
                      )
                    })()}
                  </div>
                ) : (
                  <div className="claim-action">
                  {claimSuccess && (
                    <div className="claim-success">
                      ✓ Username claimed successfully! Your historical games have been linked.
                    </div>
                  )}
                  {claimError && (
                    <div className="claim-error">{claimError}</div>
                  )}
                  <div className="claim-warning">
                    <strong>⚠️ Important:</strong> Once you claim this username on {user.platform || 'your platform'}, you cannot change it. 
                    Make sure this is the correct username you want to claim. Only one username claim is allowed per account.
                  </div>
                  <button
                    onClick={handleClaimUsername}
                    disabled={claiming}
                    className="claim-button"
                  >
                    {claiming ? 'Claiming...' : 'Claim This Username'}
                  </button>
                  <p className="claim-help-text">
                    Claiming will automatically link all your historical games to your account
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Tabs */}
        <div className="profile-tabs">
          <button
            className={`tab-button ${activeTab === 'insights' ? 'active' : ''}`}
            onClick={() => setActiveTab('insights')}
          >
            Insights
          </button>
          <button
            className={`tab-button ${activeTab === 'stats' ? 'active' : ''}`}
            onClick={() => setActiveTab('stats')}
          >
            Stats
          </button>
          <button
            className={`tab-button ${activeTab === 'games' ? 'active' : ''}`}
            onClick={() => setActiveTab('games')}
          >
            Games
          </button>
          <button
            className={`tab-button ${activeTab === 'squad' ? 'active' : ''}`}
            onClick={() => setActiveTab('squad')}
          >
            Squad
          </button>
          <button
            className={`tab-button ${activeTab === 'builds' ? 'active' : ''}`}
            onClick={() => setActiveTab('builds')}
          >
            Builds
          </button>
        </div>

        {/* Tab Content */}
        <div className="tab-content">
          {activeTab === 'insights' && (
            <>
              {/* Summary Stats */}
              <div className="card summary-stats-section">
                <h3>Summary Statistics</h3>
                <div className="summary-stats-grid">
                  <div className="summary-stat-item">
                    <div className="stat-label">PPG</div>
                    <div className="stat-value">{summary.ppg}</div>
                  </div>
                  <div className="summary-stat-item">
                    <div className="stat-label">APG</div>
                    <div className="stat-value">{summary.apg}</div>
                  </div>
                  <div className="summary-stat-item">
                    <div className="stat-label">RPG</div>
                    <div className="stat-value">{summary.rpg}</div>
                  </div>
                  <div className="summary-stat-item">
                    <div className="stat-label">Win Rate</div>
                    <div className="stat-value">{summary.winRate}%</div>
                  </div>
                  <div className="summary-stat-item">
                    <div className="stat-label">W-L</div>
                    <div className="stat-value">{summary.wins || 0}-{summary.losses || 0}</div>
                  </div>
                  <div className="summary-stat-item">
                    <div className="stat-label">TS%</div>
                    <div className="stat-value">{summary.tsPct}%</div>
                  </div>
                  <div className="summary-stat-item">
                    <div className="stat-label">FG%</div>
                    <div className="stat-value">{summary.fgPct}%</div>
                  </div>
                  <div className="summary-stat-item">
                    <div className="stat-label">3P%</div>
                    <div className="stat-value">{summary.threePct}%</div>
                  </div>
                  <div className="summary-stat-item">
                    <div className="stat-label">TO/G</div>
                    <div className="stat-value">{summary.toPerGame}</div>
                  </div>
                </div>
              </div>

              {/* Recent Trends */}
              {recentTrends && recentTrends.labels && recentTrends.labels.length > 0 && (
                <div className="card trends-section">
                  <h3>Recent Trends (Last 10 Games)</h3>
                  <div className="trends-grid">
                    <div className="trend-chart">
                      <LineChart
                        data={recentTrends.points}
                        width={350}
                        height={180}
                        color="var(--color-accent)"
                        label="Points"
                      />
                    </div>
                    <div className="trend-chart">
                      <LineChart
                        data={recentTrends.efficiency}
                        width={350}
                        height={180}
                        color="var(--color-positive)"
                        label="Efficiency"
                      />
                    </div>
                    <div className="trend-chart">
                      <LineChart
                        data={recentTrends.assists}
                        width={350}
                        height={180}
                        color="var(--color-negative)"
                        label="Assists"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Insights */}
              {insights && insights.length > 0 ? (
                <div className="card insights-section">
                  <h3>Personalized Insights</h3>
                  <div className="insights-list">
                    {insights.map((insight, index) => (
                      <div key={insight.id || index} className="insight-card">
                        <div className="insight-header">
                          <h4>{insight.title}</h4>
                          {insight.confidence && (
                            <span className={`confidence-pill confidence-${insight.confidence}`}>
                              {insight.confidence}
                            </span>
                          )}
                        </div>
                        <p className="insight-text">{insight.text}</p>
                        {insight.support && (
                          <div className="insight-support">
                            <small>
                              {insight.support.n} games • {insight.support.note}
                            </small>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ) : summary.gamesPlayed > 0 ? (
                <div className="card insights-section">
                  <h3>Personalized Insights</h3>
                  <p>No insights generated yet. Insights require specific patterns in your gameplay data.</p>
                  <p>Games played: {summary.gamesPlayed}</p>
                  <p>Insights array: {insights ? `Array with ${insights.length} items` : 'undefined'}</p>
                </div>
              ) : null}

              {/* Empty State */}
              {summary.gamesPlayed === 0 && (
                <div className="card empty-state">
                  <h3>Getting Started</h3>
                  <p>Play more games to unlock personalized insights and trends!</p>
                </div>
              )}
            </>
          )}

          {activeTab === 'stats' && (
            <div className="card">
              {statsLoading ? (
                <p>Loading stats...</p>
              ) : playerStats && playerStats.player ? (
                <>
                  {playerStats.combined_players && playerStats.combined_players > 1 && (
                    <div className="match-note" style={{ marginBottom: '20px' }}>
                      Combined {playerStats.combined_players} player records with different capitalization: {playerStats.player.variant_gamertags?.join(', ')}
                    </div>
                  )}

                  {playerStats.aggregated_stats && (
                    <div className="aggregated-stats-section">
                      <h3>Career Statistics</h3>
                      <div className="stats-grid">
                        <div className="stat-group">
                          <h4>Games</h4>
                          <div className="stat-value">{playerStats.aggregated_stats.games_played}</div>
                        </div>
                        <div className="stat-group">
                          <h4>Points</h4>
                          <div className="stat-value">
                            {playerStats.aggregated_stats.pts} total
                            {playerStats.aggregated_stats.avg_pts !== undefined && (
                              <span className="stat-avg">({playerStats.aggregated_stats.avg_pts} avg)</span>
                            )}
                          </div>
                        </div>
                        <div className="stat-group">
                          <h4>Rebounds</h4>
                          <div className="stat-value">
                            {playerStats.aggregated_stats.reb} total
                            {playerStats.aggregated_stats.avg_reb !== undefined && (
                              <span className="stat-avg">({playerStats.aggregated_stats.avg_reb} avg)</span>
                            )}
                          </div>
                        </div>
                        <div className="stat-group">
                          <h4>Assists</h4>
                          <div className="stat-value">
                            {playerStats.aggregated_stats.ast} total
                            {playerStats.aggregated_stats.avg_ast !== undefined && (
                              <span className="stat-avg">({playerStats.aggregated_stats.avg_ast} avg)</span>
                            )}
                          </div>
                        </div>
                        <div className="stat-group">
                          <h4>Steals</h4>
                          <div className="stat-value">
                            {playerStats.aggregated_stats.stl} total
                            {playerStats.aggregated_stats.avg_stl !== undefined && (
                              <span className="stat-avg">({playerStats.aggregated_stats.avg_stl} avg)</span>
                            )}
                          </div>
                        </div>
                        <div className="stat-group">
                          <h4>Blocks</h4>
                          <div className="stat-value">
                            {playerStats.aggregated_stats.blk} total
                            {playerStats.aggregated_stats.avg_blk !== undefined && (
                              <span className="stat-avg">({playerStats.aggregated_stats.avg_blk} avg)</span>
                            )}
                          </div>
                        </div>
                        <div className="stat-group">
                          <h4>Turnovers</h4>
                          <div className="stat-value">
                            {playerStats.aggregated_stats.tov} total
                            {playerStats.aggregated_stats.avg_tov !== undefined && (
                              <span className="stat-avg">({playerStats.aggregated_stats.avg_tov} avg)</span>
                            )}
                          </div>
                        </div>
                        <div className="stat-group">
                          <h4>Field Goals</h4>
                          <div className="stat-value">
                            {playerStats.aggregated_stats.fgm}/{playerStats.aggregated_stats.fga}
                            {playerStats.aggregated_stats.fg_pct !== undefined && (
                              <span className="stat-avg">({playerStats.aggregated_stats.fg_pct}%)</span>
                            )}
                          </div>
                        </div>
                        <div className="stat-group">
                          <h4>3-Pointers</h4>
                          <div className="stat-value">
                            {playerStats.aggregated_stats.tpm}/{playerStats.aggregated_stats.tpa}
                            {playerStats.aggregated_stats.tp_pct !== undefined && (
                              <span className="stat-avg">({playerStats.aggregated_stats.tp_pct}%)</span>
                            )}
                          </div>
                        </div>
                        <div className="stat-group">
                          <h4>Free Throws</h4>
                          <div className="stat-value">
                            {playerStats.aggregated_stats.ftm}/{playerStats.aggregated_stats.fta}
                            {playerStats.aggregated_stats.ft_pct !== undefined && (
                              <span className="stat-avg">({playerStats.aggregated_stats.ft_pct}%)</span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {playerStats.position_stats && Object.keys(playerStats.position_stats).length > 0 && (
                    <div className="position-stats-section" style={{ marginTop: '30px' }}>
                      <h3>Statistics by Position</h3>
                      <div className="position-stats-grid">
                        {Object.entries(playerStats.position_stats).map(([position, stats]) => (
                          <div key={position} className="position-stat-card">
                            <h4 className="position-title">{position}</h4>
                            <div className="position-stat-content">
                              <div className="position-stat-row">
                                <span className="position-stat-label">Games:</span>
                                <span className="position-stat-value">{stats.games_played}</span>
                              </div>
                              <div className="position-stat-row">
                                <span className="position-stat-label">Points:</span>
                                <span className="position-stat-value">
                                  {stats.pts} total
                                  {stats.avg_pts !== undefined && (
                                    <span className="position-stat-avg"> ({stats.avg_pts} avg)</span>
                                  )}
                                </span>
                              </div>
                              <div className="position-stat-row">
                                <span className="position-stat-label">Rebounds:</span>
                                <span className="position-stat-value">
                                  {stats.reb} total
                                  {stats.avg_reb !== undefined && (
                                    <span className="position-stat-avg"> ({stats.avg_reb} avg)</span>
                                  )}
                                </span>
                              </div>
                              <div className="position-stat-row">
                                <span className="position-stat-label">Assists:</span>
                                <span className="position-stat-value">
                                  {stats.ast} total
                                  {stats.avg_ast !== undefined && (
                                    <span className="position-stat-avg"> ({stats.avg_ast} avg)</span>
                                  )}
                                </span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {playerStats.defensive_stats && (
                    <div className="defensive-stats-section" style={{ marginTop: '30px' }}>
                      <h3>Defensive Statistics</h3>
                      <div className="defensive-stats-grid">
                        <div className="defensive-stat-group">
                          <h4>Matchups</h4>
                          <div className="defensive-stat-value">{playerStats.defensive_stats.matchups}</div>
                        </div>
                        <div className="defensive-stat-group">
                          <h4>Opponent Points</h4>
                          <div className="defensive-stat-value">
                            {playerStats.defensive_stats.opponent_pts} total
                            {playerStats.defensive_stats.avg_opponent_pts !== undefined && (
                              <span className="defensive-stat-avg">({playerStats.defensive_stats.avg_opponent_pts} avg)</span>
                            )}
                          </div>
                        </div>
                        <div className="defensive-stat-group">
                          <h4>Opponent FG%</h4>
                          <div className="defensive-stat-value">
                            {playerStats.defensive_stats.opponent_fgm}/{playerStats.defensive_stats.opponent_fga}
                            {playerStats.defensive_stats.opponent_fg_pct !== undefined && (
                              <span className="defensive-stat-avg">({playerStats.defensive_stats.opponent_fg_pct}%)</span>
                            )}
                            {playerStats.defensive_stats.fg_pct_difference !== undefined && playerStats.defensive_stats.fg_pct_difference !== null && (
                              <span className={`defensive-stat-diff ${playerStats.defensive_stats.fg_pct_difference < 0 ? 'positive' : 'negative'}`}>
                                ({playerStats.defensive_stats.fg_pct_difference > 0 ? '+' : ''}{playerStats.defensive_stats.fg_pct_difference}% vs baseline)
                              </span>
                            )}
                          </div>
                        </div>
                        {playerStats.defensive_stats.opponent_tpa > 0 && (
                          <div className="defensive-stat-group">
                            <h4>Opponent 3P%</h4>
                            <div className="defensive-stat-value">
                              {playerStats.defensive_stats.opponent_tpm}/{playerStats.defensive_stats.opponent_tpa}
                              {playerStats.defensive_stats.opponent_tp_pct !== undefined && (
                                <span className="defensive-stat-avg">({playerStats.defensive_stats.opponent_tp_pct}%)</span>
                              )}
                              {playerStats.defensive_stats.tp_pct_difference !== undefined && playerStats.defensive_stats.tp_pct_difference !== null && (
                                <span className={`defensive-stat-diff ${playerStats.defensive_stats.tp_pct_difference < 0 ? 'positive' : 'negative'}`}>
                                  ({playerStats.defensive_stats.tp_pct_difference > 0 ? '+' : ''}{playerStats.defensive_stats.tp_pct_difference}% vs baseline)
                                </span>
                              )}
                            </div>
                          </div>
                        )}
                        {playerStats.defensive_stats.opponent_fta > 0 && (
                          <div className="defensive-stat-group">
                            <h4>Opponent FT%</h4>
                            <div className="defensive-stat-value">
                              {playerStats.defensive_stats.opponent_ftm}/{playerStats.defensive_stats.opponent_fta}
                              {playerStats.defensive_stats.opponent_ft_pct !== undefined && (
                                <span className="defensive-stat-avg">({playerStats.defensive_stats.opponent_ft_pct}%)</span>
                              )}
                            </div>
                          </div>
                        )}
                        <div className="defensive-stat-group">
                          <h4>Opponent Assists</h4>
                          <div className="defensive-stat-value">
                            {playerStats.defensive_stats.opponent_ast} total
                            {playerStats.defensive_stats.avg_opponent_ast !== undefined && (
                              <span className="defensive-stat-avg">({playerStats.defensive_stats.avg_opponent_ast} avg)</span>
                            )}
                          </div>
                        </div>
                        <div className="defensive-stat-group">
                          <h4>Opponent Rebounds</h4>
                          <div className="defensive-stat-value">
                            {playerStats.defensive_stats.opponent_reb} total
                            {playerStats.defensive_stats.avg_opponent_reb !== undefined && (
                              <span className="defensive-stat-avg">({playerStats.defensive_stats.avg_opponent_reb} avg)</span>
                            )}
                          </div>
                        </div>
                        <div className="defensive-stat-group">
                          <h4>Opponent Turnovers</h4>
                          <div className="defensive-stat-value">
                            {playerStats.defensive_stats.opponent_tov} total
                            {playerStats.defensive_stats.avg_opponent_tov !== undefined && (
                              <span className="defensive-stat-avg">({playerStats.defensive_stats.avg_opponent_tov} avg)</span>
                            )}
                          </div>
                        </div>
                        <div className="defensive-stat-group">
                          <h4>Steals</h4>
                          <div className="defensive-stat-value">
                            {playerStats.defensive_stats.steals} total
                            {playerStats.defensive_stats.avg_steals !== undefined && (
                              <span className="defensive-stat-avg">({playerStats.defensive_stats.avg_steals} avg)</span>
                            )}
                          </div>
                        </div>
                        <div className="defensive-stat-group">
                          <h4>Blocks</h4>
                          <div className="defensive-stat-value">
                            {playerStats.defensive_stats.blocks} total
                            {playerStats.defensive_stats.avg_blocks !== undefined && (
                              <span className="defensive-stat-avg">({playerStats.defensive_stats.avg_blocks} avg)</span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {playerStats.defensive_stats_by_position && Object.keys(playerStats.defensive_stats_by_position).length > 0 && (
                    <div className="defensive-stats-by-position-section" style={{ marginTop: '30px' }}>
                      <h3>Defensive Statistics by Position</h3>
                      <div className="defensive-position-stats-grid">
                        {Object.entries(playerStats.defensive_stats_by_position).map(([position, stats]) => (
                          <div key={position} className="defensive-position-stat-card">
                            <h4 className="defensive-position-title">{position}</h4>
                            <div className="defensive-position-stat-content">
                              <div className="defensive-position-stat-row">
                                <span className="defensive-position-stat-label">Matchups:</span>
                                <span className="defensive-position-stat-value">{stats.matchups}</span>
                              </div>
                              <div className="defensive-position-stat-row">
                                <span className="defensive-position-stat-label">Opponent Points:</span>
                                <span className="defensive-position-stat-value">
                                  {stats.opponent_pts} total
                                  {stats.avg_opponent_pts !== undefined && (
                                    <span className="defensive-position-stat-avg"> ({stats.avg_opponent_pts} avg)</span>
                                  )}
                                </span>
                              </div>
                              <div className="defensive-position-stat-row">
                                <span className="defensive-position-stat-label">Opponent FG%:</span>
                                <span className="defensive-position-stat-value">
                                  {stats.opponent_fgm}/{stats.opponent_fga} ({stats.opponent_fg_pct}%)
                                  {stats.fg_pct_difference !== undefined && stats.fg_pct_difference !== null && (
                                    <span className={`defensive-position-stat-diff ${stats.fg_pct_difference < 0 ? 'positive' : 'negative'}`}>
                                      {' '}({stats.fg_pct_difference > 0 ? '+' : ''}{stats.fg_pct_difference}% vs baseline)
                                    </span>
                                  )}
                                </span>
                              </div>
                              {stats.opponent_tpa > 0 && (
                                <div className="defensive-position-stat-row">
                                  <span className="defensive-position-stat-label">Opponent 3P%:</span>
                                  <span className="defensive-position-stat-value">
                                    {stats.opponent_tpm}/{stats.opponent_tpa} ({stats.opponent_tp_pct}%)
                                    {stats.tp_pct_difference !== undefined && stats.tp_pct_difference !== null && (
                                      <span className={`defensive-position-stat-diff ${stats.tp_pct_difference < 0 ? 'positive' : 'negative'}`}>
                                        {' '}({stats.tp_pct_difference > 0 ? '+' : ''}{stats.tp_pct_difference}% vs baseline)
                                      </span>
                                    )}
                                  </span>
                                </div>
                              )}
                              <div className="defensive-position-stat-row">
                                <span className="defensive-position-stat-label">Opponent Assists:</span>
                                <span className="defensive-position-stat-value">
                                  {stats.opponent_ast} total
                                  {stats.avg_opponent_ast !== undefined && (
                                    <span className="defensive-position-stat-avg"> ({stats.avg_opponent_ast} avg)</span>
                                  )}
                                </span>
                              </div>
                              <div className="defensive-position-stat-row">
                                <span className="defensive-position-stat-label">Opponent Rebounds:</span>
                                <span className="defensive-position-stat-value">
                                  {stats.opponent_reb} total
                                  {stats.avg_opponent_reb !== undefined && (
                                    <span className="defensive-position-stat-avg"> ({stats.avg_opponent_reb} avg)</span>
                                  )}
                                </span>
                              </div>
                              <div className="defensive-position-stat-row">
                                <span className="defensive-position-stat-label">Opponent Turnovers:</span>
                                <span className="defensive-position-stat-value">
                                  {stats.opponent_tov} total
                                  {stats.avg_opponent_tov !== undefined && (
                                    <span className="defensive-position-stat-avg"> ({stats.avg_opponent_tov} avg)</span>
                                  )}
                                </span>
                              </div>
                              <div className="defensive-position-stat-row">
                                <span className="defensive-position-stat-label">Steals:</span>
                                <span className="defensive-position-stat-value">
                                  {stats.steals} total
                                  {stats.avg_steals !== undefined && (
                                    <span className="defensive-position-stat-avg"> ({stats.avg_steals} avg)</span>
                                  )}
                                </span>
                              </div>
                              <div className="defensive-position-stat-row">
                                <span className="defensive-position-stat-label">Blocks:</span>
                                <span className="defensive-position-stat-value">
                                  {stats.blocks} total
                                  {stats.avg_blocks !== undefined && (
                                    <span className="defensive-position-stat-avg"> ({stats.avg_blocks} avg)</span>
                                  )}
                                </span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <p>No stats available</p>
              )}
            </div>
          )}

          {activeTab === 'games' && (
            <div className="card">
              {statsLoading ? (
                <p>Loading games...</p>
              ) : playerStats && playerStats.games && playerStats.games.length > 0 ? (
                <div className="games-section">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
                    <h3>
                      Games Played ({filterGamesByPosition(filterGamesByPlatform(playerStats.games, platformFilter), gamesFilterBy).length} on this page
                      {playerStats.total_games != null && ` / ${playerStats.total_games} total`})
                    </h3>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <label htmlFor="platform-filter" style={{ fontSize: '14px' }}>Platform:</label>
                        <select
                          id="platform-filter"
                          value={platformFilter}
                          onChange={(e) => setPlatformFilter(e.target.value)}
                          style={{
                            padding: '6px 12px',
                            fontSize: '14px',
                            borderRadius: '4px',
                            border: '1px solid var(--color-border)',
                            cursor: 'pointer'
                          }}
                        >
                          <option value="ALL">All Platforms</option>
                          <option value="PC">PC</option>
                          <option value="Console">Console</option>
                        </select>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <label htmlFor="games-filter" style={{ fontSize: '14px' }}>Position:</label>
                        <select
                          id="games-filter"
                          value={gamesFilterBy}
                          onChange={(e) => setGamesFilterBy(e.target.value)}
                          style={{
                            padding: '6px 12px',
                            fontSize: '14px',
                            borderRadius: '4px',
                            border: '1px solid var(--color-border)',
                            cursor: 'pointer'
                          }}
                        >
                          <option value="all">All Positions</option>
                          <option value="PG">PG</option>
                          <option value="SG">SG</option>
                          <option value="SF">SF</option>
                          <option value="PF">PF</option>
                          <option value="C">C</option>
                        </select>
                      </div>
                    </div>
                  </div>
                  <div className="games-table-container">
                    <table>
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Position</th>
                          {user && verifiedClaim && verifiedClaim.display_name?.toLowerCase() === username?.toLowerCase() && (
                            <th>Build</th>
                          )}
                          <th>Team</th>
                          <th>Score</th>
                          <th>Opponent</th>
                          <th>PTS</th>
                          <th>REB</th>
                          <th>AST</th>
                          <th>STL</th>
                          <th>BLK</th>
                          <th>Grade</th>
                          <th>Details</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filterGamesByPosition(filterGamesByPlatform(playerStats.games, platformFilter), gamesFilterBy).map((game, idx) => (
                          <tr key={idx}>
                            <td>{formatDate(game.created_at)}</td>
                            <td>{game.position}</td>
                            {user && verifiedClaim && verifiedClaim.display_name?.toLowerCase() === username?.toLowerCase() && (
                              <td>
                                {game.game_player_row_id ? (
                                  gamesBuilds.length > 0 ? (
                                    <select
                                      value={game.build?.build_id || ''}
                                      onChange={(e) => {
                                        const buildId = e.target.value === '' ? null : parseInt(e.target.value)
                                        handleGameBuildChange(game.game_id, game.game_player_row_id, buildId)
                                      }}
                                      disabled={assigningBuild[game.game_player_row_id]}
                                      style={{
                                        padding: '4px 8px',
                                        fontSize: '12px',
                                        minWidth: '120px',
                                        borderRadius: '4px',
                                        border: '1px solid var(--color-border)',
                                        cursor: assigningBuild[game.game_player_row_id] ? 'wait' : 'pointer'
                                      }}
                                    >
                                      <option value="">None</option>
                                      {gamesBuilds.map(build => (
                                        <option key={build.id} value={build.id}>
                                          {formatBuildName(build.display_name)}
                                        </option>
                                      ))}
                                    </select>
                                  ) : (
                                    <span style={{ color: 'var(--color-text-secondary)', fontSize: '12px' }}>Loading...</span>
                                  )
                                ) : (
                                  <span style={{ color: 'var(--color-text-secondary)', fontSize: '12px' }}>N/A</span>
                                )}
                              </td>
                            )}
                            <td>{game.team_side}</td>
                            <td className="score-cell">
                              {game.team_score} - {game.opponent_score}
                            </td>
                            <td>{game.opponent_team}</td>
                            <td>{game.stats.pts}</td>
                            <td>{game.stats.reb}</td>
                            <td>{game.stats.ast}</td>
                            <td>{game.stats.stl}</td>
                            <td>{game.stats.blk}</td>
                            <td>{game.grade || '-'}</td>
                            <td>
                              <Link to={`/games/${game.game_id}`}>View</Link>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {playerStats.total_pages != null && playerStats.total_pages > 1 && (
                    <div className="games-pagination" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '16px', marginTop: '16px', flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        onClick={() => setGamesPage(p => Math.max(1, p - 1))}
                        disabled={playerStats.page <= 1 || statsLoading}
                        style={{
                          padding: '8px 16px',
                          cursor: playerStats.page <= 1 || statsLoading ? 'not-allowed' : 'pointer',
                          opacity: playerStats.page <= 1 ? 0.6 : 1
                        }}
                      >
                        Previous
                      </button>
                      <span style={{ fontSize: '14px' }}>
                        Page {playerStats.page} of {playerStats.total_pages}
                      </span>
                      <button
                        type="button"
                        onClick={() => setGamesPage(p => Math.min(playerStats.total_pages, p + 1))}
                        disabled={playerStats.page >= playerStats.total_pages || statsLoading}
                        style={{
                          padding: '8px 16px',
                          cursor: playerStats.page >= playerStats.total_pages || statsLoading ? 'not-allowed' : 'pointer',
                          opacity: playerStats.page >= playerStats.total_pages ? 0.6 : 1
                        }}
                      >
                        Next
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <p>No games found for this player.</p>
              )}
            </div>
          )}

          {activeTab === 'squad' && (
            <div className="card squad-section">
              <h3>Squad Chemistry</h3>
              <p className="squad-intro">
                Rec games have no fixed teams, so this is built from who actually
                shared a court with {profile?.username || username || 'this player'} across
                {chemistry ? ` ${chemistry.gamesAnalyzed}` : ''} recorded games —
                the teammates they win with, and the players they’ve faced most.
              </p>

              {chemistryLoading && <p className="squad-loading">Crunching lineups…</p>}
              {chemistryError && <p className="squad-error">Couldn’t load chemistry: {chemistryError}</p>}

              {chemistry && !chemistryLoading && (
                <div className="squad-grids">
                  <div className="squad-col">
                    <h4 className="squad-col-title">Plays with</h4>
                    {chemistry.teammates.length === 0 ? (
                      <p className="squad-empty">No recurring teammates yet — needs at least two games together.</p>
                    ) : (
                      <ul className="squad-list">
                        {chemistry.teammates.map((t) => (
                          <li key={t.gamertag} className="squad-row">
                            <Link to={`/players/${encodeURIComponent(t.gamertag)}`} className="squad-name">
                              {t.gamertag}
                            </Link>
                            <span className="squad-record">{t.wins}-{t.losses}</span>
                            <span className="squad-games">{t.games} gp</span>
                            <span className={`squad-winrate ${t.winRate >= 50 ? 'good' : 'bad'}`}>
                              {t.winRate}%
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="squad-col">
                    <h4 className="squad-col-title">Plays against</h4>
                    {chemistry.rivals.length === 0 ? (
                      <p className="squad-empty">No recurring opponents yet.</p>
                    ) : (
                      <ul className="squad-list">
                        {chemistry.rivals.map((t) => (
                          <li key={t.gamertag} className="squad-row">
                            <Link to={`/players/${encodeURIComponent(t.gamertag)}`} className="squad-name">
                              {t.gamertag}
                            </Link>
                            <span className="squad-record">{t.wins}-{t.losses}</span>
                            <span className="squad-games">{t.games} gp</span>
                            <span className={`squad-winrate ${t.winRate >= 50 ? 'good' : 'bad'}`}>
                              {t.winRate}%
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'builds' && (
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <h3>{user && verifiedClaim && verifiedClaim.display_name?.toLowerCase() === username?.toLowerCase() ? 'My Builds' : 'Builds'}</h3>
                {user && verifiedClaim && verifiedClaim.display_name?.toLowerCase() === username?.toLowerCase() && (
                  <button
                    onClick={() => setShowAddBuildModal(true)}
                    style={{
                      padding: '8px 16px',
                      backgroundColor: 'var(--color-accent)',
                      color: 'white',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: 'pointer'
                    }}
                  >
                    Add Build
                  </button>
                )}
              </div>

              {buildsLoading ? (
                <p>Loading builds...</p>
              ) : buildError ? (
                <p className="error">{buildError}</p>
              ) : builds.length === 0 ? (
                <p>
                  {user && verifiedClaim && verifiedClaim.display_name?.toLowerCase() === username?.toLowerCase()
                    ? 'No builds yet. Click "Add Build" to upload a build sheet screenshot.'
                    : 'No builds available for this player.'}
                </p>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '20px' }}>
                  {builds.map((build) => (
                    <div
                      key={build.id}
                      style={{
                        border: '1px solid var(--color-border)',
                        borderRadius: '8px',
                        padding: '16px',
                        backgroundColor: 'var(--color-surface-2)'
                      }}
                    >
                      <h4 style={{ marginTop: 0 }}>{formatBuildName(build.display_name)}</h4>
                      <p style={{ margin: '8px 0', color: 'var(--color-text-secondary)' }}>
                        {build.position && `${build.position} • `}
                        {build.archetype || 'No archetype'}
                      </p>
                      {build.height && build.weight_lbs && build.wingspan && (
                        <p style={{ margin: '4px 0', fontSize: '14px', color: 'var(--color-text-secondary)' }}>
                          HT: {build.height} • WT: {build.weight_lbs}lbs • WS: {build.wingspan}
                        </p>
                      )}
                      {build.overall_current && (
                        <p style={{ margin: '4px 0', fontSize: '14px', color: 'var(--color-text-secondary)' }}>
                          OVR: {build.overall_current}
                          {build.overall_max && ` / ${build.overall_max} MAX`}
                        </p>
                      )}
                      <div style={{ marginTop: '12px', display: 'flex', gap: '8px' }}>
                        <button
                          onClick={() => setShowBuildDetailModal(build.id)}
                          style={{
                            padding: '6px 12px',
                            backgroundColor: 'var(--color-positive)',
                            color: 'white',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '14px'
                          }}
                        >
                          View
                        </button>
                        {user && verifiedClaim && verifiedClaim.display_name?.toLowerCase() === username?.toLowerCase() && (
                          <button
                            onClick={async () => {
                              if (window.confirm(`Delete build "${build.display_name}"?`)) {
                                try {
                                  await deleteBuild(build.id)
                                  setBuilds(builds.filter(b => b.id !== build.id))
                                } catch (err) {
                                  alert('Failed to delete build: ' + err.message)
                                }
                              }
                            }}
                            style={{
                              padding: '6px 12px',
                              backgroundColor: 'var(--color-negative)',
                              color: 'white',
                              border: 'none',
                              borderRadius: '4px',
                              cursor: 'pointer',
                              fontSize: '14px'
                            }}
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

        </div>
      </div>
      <Footer />

      {/* Add Build Modal */}
      {showAddBuildModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000
          }}
          onClick={() => !uploadingBuild && setShowAddBuildModal(false)}
        >
          <div
            style={{
              backgroundColor: 'white',
              padding: '24px',
              borderRadius: '8px',
              maxWidth: '500px',
              width: '90%',
              maxHeight: '90vh',
              overflow: 'auto'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ marginTop: 0 }}>Add Build</h3>
            <p style={{ color: 'var(--color-text-secondary)', marginBottom: '16px' }}>
              Upload a screenshot of the "Attribute Upgrades - Simple View" build sheet.
            </p>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
              <input
                type="checkbox"
                checked={newBuildIsPublic}
                onChange={(e) => setNewBuildIsPublic(e.target.checked)}
                disabled={uploadingBuild}
              />
              Make this build public
            </label>
            <p style={{ color: 'var(--color-text-secondary)', marginTop: 0, marginBottom: '12px', fontSize: '13px' }}>
              Builds are private by default.
            </p>
            <input
              type="file"
              accept="image/*"
              onChange={async (e) => {
                const file = e.target.files[0]
                if (!file) return

                setUploadingBuild(true)
                setBuildError(null)
                try {
                  const newBuild = await ingestBuildSheet(file, null, newBuildIsPublic)
                  setBuilds([newBuild, ...builds])
                  setShowAddBuildModal(false)
                  setNewBuildIsPublic(false)
                } catch (err) {
                  setBuildError(err.message || 'Failed to upload build')
                } finally {
                  setUploadingBuild(false)
                }
              }}
              disabled={uploadingBuild}
              style={{ marginBottom: '16px' }}
            />
            {uploadingBuild && <p>Processing build sheet...</p>}
            {buildError && <p style={{ color: 'red' }}>{buildError}</p>}
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => {
                  setShowAddBuildModal(false)
                  setBuildError(null)
                  setNewBuildIsPublic(false)
                }}
                disabled={uploadingBuild}
                style={{
                  padding: '8px 16px',
                  backgroundColor: 'var(--color-text-secondary)',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: uploadingBuild ? 'not-allowed' : 'pointer'
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Build Detail Modal */}
      {showBuildDetailModal && (
        <BuildDetailModal
          buildId={showBuildDetailModal}
          onClose={() => setShowBuildDetailModal(null)}
        />
      )}
      </div>
    </div>
  )
}

// Build Detail Modal Component
function BuildDetailModal({ buildId, onClose }) {
  const [build, setBuild] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const loadBuild = async () => {
      try {
        const data = await getBuild(buildId)
        setBuild(data)
      } catch (err) {
        console.error('Failed to load build:', err)
      } finally {
        setLoading(false)
      }
    }
    loadBuild()
  }, [buildId])

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: 'white',
          padding: '24px',
          borderRadius: '8px',
          maxWidth: '800px',
          width: '90%',
          maxHeight: '90vh',
          overflow: 'auto'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {loading ? (
          <p>Loading...</p>
        ) : build ? (
          <>
            <h3 style={{ marginTop: 0 }}>{formatBuildName(build.display_name)}</h3>
            <div style={{ marginBottom: '16px' }}>
              {build.position && <p><strong>Position:</strong> {build.position}</p>}
              {build.archetype && <p><strong>Archetype:</strong> {build.archetype}</p>}
              {build.height && <p><strong>Height:</strong> {build.height}</p>}
              {build.weight_lbs && <p><strong>Weight:</strong> {build.weight_lbs} lbs</p>}
              {build.wingspan && <p><strong>Wingspan:</strong> {build.wingspan}</p>}
              {build.overall_current && (
                <p>
                  <strong>Overall:</strong> {build.overall_current}
                  {build.overall_max && ` / ${build.overall_max} MAX`}
                </p>
              )}
            </div>
            
            {/* Build Sheet Screenshot */}
            {build.screenshot_url && (
              <div style={{ marginBottom: '24px' }}>
                <h4>Build Sheet Screenshot</h4>
                <img
                  src={apiUrl(build.screenshot_url)}
                  alt="Build sheet screenshot"
                  style={{
                    maxWidth: '100%',
                    height: 'auto',
                    border: '1px solid var(--color-border)',
                    borderRadius: '4px',
                    marginTop: '8px'
                  }}
                />
              </div>
            )}
            
            <h4>Attributes</h4>
            {build.attributes_by_category && Object.entries(build.attributes_by_category).map(([category, attrs]) => (
              <div key={category} style={{ marginBottom: '20px' }}>
                <h5 style={{ marginBottom: '8px', color: 'var(--color-accent)' }}>{category}</h5>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '8px' }}>
                  {attrs.map((attr, idx) => (
                    <div key={idx} style={{ fontSize: '14px' }}>
                      <strong>{attr.name}:</strong> {attr.current}
                      {attr.max && ` / ${attr.max} MAX`}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <button
              onClick={onClose}
              style={{
                marginTop: '16px',
                padding: '8px 16px',
                backgroundColor: 'var(--color-text-secondary)',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer'
              }}
            >
              Close
            </button>
          </>
        ) : (
          <p>Build not found</p>
        )}
      </div>
    </div>
  )
}

export default PlayerProfilePage
