import { useState, useEffect, useMemo, useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { fetchGames } from '../utils/api'
import PageLayout from '../components/PageLayout'
import GameVersionSwitch from '../components/GameVersionSwitch'
import { useGameVersion, normalizeGameVersion } from '../contexts/GameVersionContext'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import './GamesListPage.css'

const PER_PAGE = 25

/** Build search string for current list state so "Back to Games" can restore position */
function gamesListSearchString({ page, sort, filter, platform, gameVersion }) {
  const params = new URLSearchParams()
  if (page > 1) params.set('page', String(page))
  if (sort !== 'date_desc') params.set('sort', sort)
  if (filter !== 'all') params.set('filter', filter)
  if (platform !== 'all') params.set('platform', platform)
  if (gameVersion) params.set('game_version', gameVersion)
  const s = params.toString()
  return s ? `?${s}` : ''
}

function GamesListPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const pageFromUrl = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1)
  const sortFromUrl = searchParams.get('sort') || 'date_desc'
  const filterFromUrl = searchParams.get('filter') || 'all'
  const platformFromUrl = searchParams.get('platform') || 'all'
  const gameVersionFromUrl = searchParams.get('game_version')

  const { gameVersion, setGameVersion } = useGameVersion()

  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState(filterFromUrl)
  const [sort, setSort] = useState(sortFromUrl)
  const [platform, setPlatform] = useState(platformFromUrl)
  const [page, setPage] = useState(pageFromUrl)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)

  const returnToSearch = useMemo(
    () => gamesListSearchString({ page, sort, filter, platform, gameVersion }),
    [page, sort, filter, platform, gameVersion]
  )

  // A shared link carries its own title; adopt it once so the deep link lands
  // on the games the sender was looking at.
  useEffect(() => {
    if (gameVersionFromUrl) {
      setGameVersion(normalizeGameVersion(gameVersionFromUrl, gameVersion))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const didMountRef = useRef(false)
  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true
      return
    }
    setPage(1)
  }, [filter, sort, platform, gameVersion])

  useEffect(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (page > 1) next.set('page', String(page))
      else next.delete('page')
      if (sort !== 'date_desc') next.set('sort', sort)
      else next.delete('sort')
      if (filter !== 'all') next.set('filter', filter)
      else next.delete('filter')
      if (platform !== 'all') next.set('platform', platform)
      else next.delete('platform')
      next.set('game_version', gameVersion)
      return next
    }, { replace: true })
  }, [page, sort, filter, platform, gameVersion])

  useEffect(() => {
    loadGames()
  }, [filter, sort, platform, gameVersion, page])

  const loadGames = async () => {
    setLoading(true)
    setError(null)
    
    try {
      const data = await fetchGames(filter, sort, page, platform, gameVersion)
      setGames(data.games)
      setTotal(data.total)
      setTotalPages(data.total_pages)
    } catch (err) {
      setError(err.message || 'Failed to load games')
    } finally {
      setLoading(false)
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

  if (loading) {
    return (
      <PageLayout title="Games List">
        <div className="loading">Loading games...</div>
      </PageLayout>
    )
  }

  if (error) {
    return (
      <PageLayout title="Games List">
        <div className="error-message">
          <strong>Error:</strong> {error}
          <Button onClick={loadGames} style={{ marginTop: 'var(--spacing-sm)' }}>
            Retry
          </Button>
        </div>
      </PageLayout>
    )
  }

  return (
    <PageLayout title="Games List">

      <Card className="games-filters">
        <div className="filters-row">
          <GameVersionSwitch className="filter-group" />

          <div className="filter-group">
            <label htmlFor="filter">Filter:</label>
            <select
              id="filter"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="all">All Games</option>
              <option value="needs_verification">Needs Verification</option>
              <option value="incomplete_data">Incomplete Data</option>
            </select>
          </div>
          
          <div className="filter-group">
            <label htmlFor="sort">Sort:</label>
            <select
              id="sort"
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              <option value="date_desc">Newest First</option>
              <option value="date_asc">Oldest First</option>
              <option value="needs_verification_first">Needs Verification First</option>
            </select>
          </div>

          <div className="filter-group">
            <label htmlFor="platform">Platform:</label>
            <select
              id="platform"
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
            >
              <option value="all">All</option>
              <option value="PC">PC</option>
              <option value="Console">Console</option>
            </select>
          </div>
          
          {total > 0 && (
            <div className="games-count">
              Showing {(page - 1) * PER_PAGE + 1}–{Math.min(page * PER_PAGE, total)} of {total} game{total !== 1 ? 's' : ''}
            </div>
          )}
        </div>
      </Card>

      {!loading && total === 0 ? (
        <EmptyState 
          title={filter === 'all' ? `No ${gameVersion} games found` : 'No matching games'}
          message={
            filter === 'all' 
              ? `No ${gameVersion} games have been uploaded yet. Upload a screenshot, or switch titles above.`
              : `No ${gameVersion} games found matching the "${filter === 'needs_verification' ? 'Needs Verification' : 'Incomplete Data'}" filter.`
          }
          action={
            <>
              {filter !== 'all' && (
                <Button onClick={() => setFilter('all')}>
                  Show All Games
                </Button>
              )}
              {filter === 'all' && (
                <Link to="/">
                  <Button>Go to Upload Page</Button>
                </Link>
              )}
            </>
          }
        />
      ) : (
        <Card>
          <div className="games-table-container">
            <table>
              <thead>
                <tr>
                  <th>Teams</th>
                  <th>Score</th>
                  <th>Date</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {games.map((game) => (
                  <tr key={game.id}>
                    <td>
                      {game.away_team} vs {game.home_team}
                    </td>
                    <td className="score-cell">
                      <div className="score-with-icons">
                        {game.needs_verification && (
                          <span 
                            title="Data needs verification" 
                            className="warning-icon"
                          >
                            ⚠️
                          </span>
                        )}
                        {game.has_incomplete_data && (
                          <span 
                            title="Incomplete data - some players are missing stats" 
                            className="error-icon"
                          >
                            ⚠️
                          </span>
                        )}
                        <span>{game.away_score} - {game.home_score}</span>
                      </div>
                    </td>
                    <td>{formatDate(game.created_at)}</td>
                    <td>
                      <Link to={`/games/${game.id}`} state={{ returnToSearch }}>View Details</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="games-pagination">
              <Button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                aria-label="Previous page"
              >
                Previous
              </Button>
              <div className="games-page-selector">
                <label htmlFor="page-select">Page:</label>
                <select
                  id="page-select"
                  value={page}
                  onChange={(e) => setPage(Number(e.target.value))}
                  aria-label="Select page"
                >
                  {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                    <option key={p} value={p}>
                      {p} of {totalPages}
                    </option>
                  ))}
                </select>
              </div>
              <Button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                aria-label="Next page"
              >
                Next
              </Button>
            </div>
          )}
        </Card>
      )}
    </PageLayout>
  )
}

export default GamesListPage

