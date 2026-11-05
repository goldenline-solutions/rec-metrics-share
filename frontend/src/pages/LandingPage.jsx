import { useState, useEffect, useRef, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import PageLayout from '../components/PageLayout'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import SectionHeader from '../components/ui/SectionHeader'
import Badge from '../components/ui/Badge'
import Seo from '../components/Seo'
import { getPlayerSuggestions, getLeaderboard, getSiteStats } from '../utils/api'
import { getTemplates } from '../utils/planner'
import './LandingPage.css'

// Feature highlights for the Build Planner — the site's flagship tool.
const BUILDER_FEATURES = [
  { title: 'Live overall & soft caps', body: 'Drag any attribute and watch your OVR update instantly. Every slider shows its budget ceiling so you never overspend.' },
  { title: 'Badges & takeovers', body: 'See exactly which badges you unlock and at what tier — Bronze through Legend — plus every takeover your build qualifies for.' },
  { title: 'Thousands of animations', body: 'Filter dribble moves, dunk packages, and jumpshots down to the ones your build actually meets the requirements for.' },
  { title: 'Templates & cap breakers', body: 'Start from a proven build and tweak from there, then push a maxed 99 past its caps with cap breakers.' },
]

const DEBOUNCE_MS = 200
const LEADERBOARD_LIMIT = 10
const MIN_GAMES = 5
const LEADERBOARD_CACHE_KEY = 'recmetrics_leaderboard_preview'

/** Discord invite URL from env (same as Footer). */
const DISCORD_INVITE = import.meta.env.VITE_DISCORD_INVITE || '#'

/** True if both dates are on the same UTC calendar day (cache valid until midnight UTC). */
function isSameUTCDay(isoString, now = new Date()) {
  if (!isoString) return false
  const d = new Date(isoString)
  return d.getUTCFullYear() === now.getUTCFullYear() &&
    d.getUTCMonth() === now.getUTCMonth() &&
    d.getUTCDate() === now.getUTCDate()
}

function formatLastUpdated(isoString) {
  if (!isoString) return ''
  const date = new Date(isoString)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)
  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

/**
 * Player search input with autocomplete dropdown. Selecting a suggestion
 * navigates to /players/:username. Uses debounced getPlayerSuggestions and
 * aborts in-flight requests when query changes.
 */
function PlayerSearchBox({ onNavigate }) {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const debounceRef = useRef(null)
  const abortRef = useRef(null)
  const wrapperRef = useRef(null)

  const fetchSuggestions = useCallback(async (q) => {
    if (abortRef.current) abortRef.current.abort()
    const ac = new AbortController()
    abortRef.current = ac
    setLoading(true)
    setSuggestions([])
    try {
      const data = await getPlayerSuggestions(q, 10, ac.signal)
      if (!ac.signal.aborted) {
        setSuggestions(data.suggestions || [])
      }
    } catch (err) {
      if (err.name !== 'AbortError' && !ac.signal.aborted) setSuggestions([])
    } finally {
      if (!ac.signal.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const q = query.trim()
    if (!q) {
      setSuggestions([])
      setLoading(false)
      setOpen(false)
      return
    }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setOpen(true)
      fetchSuggestions(q)
    }, DEBOUNCE_MS)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query, fetchSuggestions])

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleSelect = (gamertag) => {
    setQuery('')
    setSuggestions([])
    setOpen(false)
    onNavigate(gamertag)
  }

  return (
    <div className="landing-search-wrap" ref={wrapperRef}>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => query.trim() && setOpen(true)}
        placeholder="Search by gamertag..."
        className="landing-search-input"
        aria-label="Search player"
        autoComplete="off"
      />
      {loading && <span className="landing-search-loading" aria-hidden>Searching...</span>}
      {open && (suggestions.length > 0 || (query.trim() && !loading)) && (
        <ul className="landing-search-dropdown" role="listbox">
          {suggestions.length === 0 && !loading && (
            <li className="landing-search-dropdown-empty">No players found</li>
          )}
          {suggestions.map((s) => (
            <li
              key={s.gamertag}
              role="option"
              className="landing-search-dropdown-item"
              onMouseDown={(e) => { e.preventDefault(); handleSelect(s.gamertag) }}
            >
              {s.gamertag}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * Mini leaderboard: top 10 by PTS, with Rank, Player, PTS, REB, AST.
 * Uses existing getLeaderboard(stat, limit, minGames, position, platform).
 */
function MiniLeaderboardPreview() {
  const [data, setData] = useState(null)
  const [fetchedAt, setFetchedAt] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchAndCache = useCallback((skipCache = false) => {
    if (!skipCache) {
      try {
        const raw = localStorage.getItem(LEADERBOARD_CACHE_KEY)
        if (raw) {
          const { data: cached, fetchedAt: at } = JSON.parse(raw)
          if (cached && at && isSameUTCDay(at)) {
            setData(cached)
            setFetchedAt(at)
            setLoading(false)
            setError(null)
            return
          }
        }
      } catch {
        // ignore invalid cache
      }
    } else {
      try {
        localStorage.removeItem(LEADERBOARD_CACHE_KEY)
      } catch {
        // ignore
      }
    }

    setLoading(true)
    setError(null)
    getLeaderboard('pts', LEADERBOARD_LIMIT, MIN_GAMES, 'ALL', 'ALL')
      .then((res) => {
        setData(res)
        const at = new Date().toISOString()
        setFetchedAt(at)
        try {
          localStorage.setItem(LEADERBOARD_CACHE_KEY, JSON.stringify({ data: res, fetchedAt: at }))
        } catch {
          // ignore quota / private mode
        }
      })
      .catch((err) => {
        setError(err.message || 'Failed to load')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    fetchAndCache(false)
  }, [fetchAndCache])

  if (loading) {
    return (
      <div className="landing-mini-leaderboard">
        <div className="landing-table-skeleton">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="landing-skeleton-row" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="landing-mini-leaderboard landing-mini-leaderboard-error">
        <p>{error}</p>
        <Button variant="outline" size="sm" onClick={() => fetchAndCache(true)}>
          Retry
        </Button>
      </div>
    )
  }

  const list = data?.leaderboard || []
  return (
    <div className="landing-mini-leaderboard">
      <div className="landing-table-wrap">
        <table className="landing-mini-table">
          <thead>
            <tr>
              <th>Rank</th>
              <th>Player</th>
              <th>PTS</th>
              <th>REB</th>
              <th>AST</th>
            </tr>
          </thead>
          <tbody>
            {list.length === 0 ? (
              <tr>
                <td colSpan={5} className="landing-mini-empty">
                  No leaderboard data yet.
                </td>
              </tr>
            ) : list.map((row) => (
              <tr key={row.player_id ?? row.gamertag}>
                <td>
                  <Badge variant={row.rank <= 3 ? 'positive' : 'default'}>{row.rank}</Badge>
                </td>
                <td>
                  <Link to={`/players/${encodeURIComponent(row.gamertag)}`}>
                    {row.gamertag}
                  </Link>
                </td>
                <td>{row.pts != null ? row.pts.toLocaleString() : '—'}</td>
                <td>{row.reb != null ? row.reb.toLocaleString() : '—'}</td>
                <td>{row.ast != null ? row.ast.toLocaleString() : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="landing-mini-leaderboard-footer">
        {fetchedAt && (
          <span
            className="landing-mini-updated"
            title={new Date(fetchedAt).toLocaleString()}
          >
            Updated {formatLastUpdated(fetchedAt)}
          </span>
        )}
        <Link to="/leaderboard" className="landing-view-full">
          View full leaderboard
        </Link>
      </div>
    </div>
  )
}

export default function LandingPage() {
  const navigate = useNavigate()
  const [stats, setStats] = useState(null)
  const [templateCount, setTemplateCount] = useState(null)

  useEffect(() => {
    let cancelled = false
    getSiteStats()
      .then((s) => { if (!cancelled) setStats(s) })
      .catch(() => { if (!cancelled) setStats(null) })
    // Template count is a nice hero detail; if the planner service is down we
    // simply omit it rather than block the page.
    getTemplates()
      .then((res) => { if (!cancelled) setTemplateCount(res.templates?.length ?? null) })
      .catch(() => { if (!cancelled) setTemplateCount(null) })
    return () => { cancelled = true }
  }, [])

  const handleSearchPlayer = (gamertag) => {
    navigate(`/players/${encodeURIComponent(gamertag)}`)
  }

  return (
    <PageLayout className="landing-page-layout">
      <Seo
        title="RecMetrics — NBA 2K26 Build Planner"
        description="Plan your perfect NBA 2K26 build with a live overall, soft caps, badges, takeovers, and animations. Start from 270+ template builds, then track your REC stats and leaderboards."
        path="/"
      />
      <div className="landing-page">
        <section className="landing-hero">
          <span className="landing-hero-eyebrow">NBA 2K26 Build Planner</span>
          <h1 className="landing-hero-title">
            Plan your perfect <span className="accent">build</span>
          </h1>
          <p className="landing-hero-subtext">
            Dial in every attribute with a live overall, soft caps, badges, takeovers, and animations —
            before you spend a single skill point.
          </p>
          <p className="landing-hero-stats">
            {templateCount ? `${templateCount} template builds to start from · ` : ''}
            live badge &amp; animation preview
          </p>
          <div className="landing-hero-ctas">
            <Link to="/builds/new" className="btn btn-primary btn-lg landing-cta-primary">
              Open the Build Planner
            </Link>
            <Link to="/builds/templates" className="btn btn-outline btn-lg landing-cta-secondary">
              Browse templates
            </Link>
          </div>
        </section>

        <section className="landing-features">
          <SectionHeader title="What the planner does" />
          <div className="landing-feature-cards landing-builder-features">
            {BUILDER_FEATURES.map((f) => (
              <Card className="landing-feature-card" key={f.title}>
                <h3>{f.title}</h3>
                <p>{f.body}</p>
              </Card>
            ))}
          </div>
          <div className="landing-features-cta">
            <Link to="/builds/new" className="btn btn-primary landing-cta-primary">Start building</Link>
            <span className="landing-features-cta-note">No login needed — sign in only to save your build.</span>
          </div>
        </section>

        {/* Stats & leaderboards — still here, but a secondary act behind the builder. */}
        <section className="landing-stats-secondary">
          <SectionHeader title="Also on RecMetrics: stats & leaderboards" />
          <p className="landing-section-lead">
            Track your REC games, grades, and standings. Stats come from screenshots you
            upload — <Link to="/upload">upload yours</Link> to get on the board.
          </p>
          <div className="landing-instant-grid">
            <Card className="landing-search-card">
              <h3 className="landing-search-card-title">Find a player</h3>
              <PlayerSearchBox onNavigate={handleSearchPlayer} />
              <p className="landing-search-hint">Type to see suggestions, then select to open profile.</p>
            </Card>
            <Card className="landing-mini-card">
              <h3 className="landing-mini-card-title">Top 10 by points</h3>
              <MiniLeaderboardPreview />
            </Card>
          </div>
          {stats && (stats.games_tracked > 0 || stats.players_tracked > 0) && (
            <p className="landing-stats-line">
              {stats.games_tracked.toLocaleString()} games tracked · {stats.players_tracked.toLocaleString()} players
            </p>
          )}
        </section>

        <section className="landing-community">
          <SectionHeader title="Join the community" />
          <Card className="landing-community-card">
            <div className="landing-community-content">
              <p className="landing-community-lead">
                Join our Discord to connect with other REC players, use the RecMetrics bot to upload
                game screenshots directly from Discord, and report issues or bad data so we can keep
                stats accurate.
              </p>
              <ul className="landing-community-list">
                <li>Upload screenshots through Discord — no need to leave the app</li>
                <li>Report bugs, bad data, or feature requests in one place</li>
                <li>Chat with the community and get the latest updates</li>
              </ul>
              <a
                href={DISCORD_INVITE}
                target="_blank"
                rel="noopener noreferrer"
                className="landing-community-cta"
              >
                Join Discord
              </a>
            </div>
          </Card>
        </section>
      </div>
    </PageLayout>
  )
}
