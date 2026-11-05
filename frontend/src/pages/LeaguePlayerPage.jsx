import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import * as league from '../utils/leagueApi'
import LeagueLoginButton from '../components/LeagueLoginButton'
import './LeaguePage.css'

// The 2K attribute groups, in the order 2K itself shows them. Mirrors
// ATTRIBUTE_GROUPS in backend/nba2k_models.py.
const GROUPS = [
  ['Outside Scoring', ['closeShot', 'midRangeShot', 'threePointShot', 'freeThrow', 'shotIQ', 'offensiveConsistency']],
  ['Inside Scoring', ['drivingLayup', 'standingDunk', 'drivingDunk', 'postControl', 'postHook', 'postFade', 'drawFoul', 'hands']],
  ['Athleticism', ['speed', 'agility', 'strength', 'vertical', 'stamina', 'hustle', 'durability']],
  ['Playmaking', ['passAccuracy', 'ballHandle', 'speedWithBall', 'passIQ', 'passVision', 'passPerception']],
  ['Defense', ['interiorDefense', 'perimeterDefense', 'steal', 'block', 'helpDefenseIQ', 'defensiveConsistency']],
  ['Rebounding', ['offensiveRebound', 'defensiveRebound']],
]

const LABELS = {
  closeShot: 'Close Shot', midRangeShot: 'Mid-Range', threePointShot: 'Three-Point',
  freeThrow: 'Free Throw', shotIQ: 'Shot IQ', offensiveConsistency: 'Off. Consistency',
  drivingLayup: 'Driving Layup', standingDunk: 'Standing Dunk', drivingDunk: 'Driving Dunk',
  postControl: 'Post Control', postHook: 'Post Hook', postFade: 'Post Fade',
  drawFoul: 'Draw Foul', hands: 'Hands',
  speed: 'Speed', agility: 'Agility', strength: 'Strength', vertical: 'Vertical',
  stamina: 'Stamina', hustle: 'Hustle', durability: 'Durability',
  passAccuracy: 'Pass Accuracy', ballHandle: 'Ball Handle', speedWithBall: 'Speed With Ball',
  passIQ: 'Pass IQ', passVision: 'Pass Vision', passPerception: 'Pass Perception',
  interiorDefense: 'Interior D', perimeterDefense: 'Perimeter D', steal: 'Steal',
  block: 'Block', helpDefenseIQ: 'Help Defense IQ', defensiveConsistency: 'Def. Consistency',
  offensiveRebound: 'Off. Rebound', defensiveRebound: 'Def. Rebound',
}

const tier = (v) => (v >= 95 ? 'elite' : v >= 85 ? 'high' : v >= 70 ? 'mid' : 'low')

// "Hall of Fame" would otherwise become three class names.
const tierClass = (level) =>
  String(level || 'none').toLowerCase().replace(/\s+/g, '-')

/**
 * Badges come back in whatever shape the API gives them, and the list endpoint
 * returns an empty object. Flatten the plausible shapes into {name, level} and
 * let the caller say "not synced yet" when nothing comes out.
 */
function normalizeBadges(badges) {
  if (!badges || typeof badges !== 'object') return []
  if (Array.isArray(badges)) {
    return badges.map((b) =>
      typeof b === 'string'
        ? { name: b, level: null, category: null }
        : {
            name: b.name || b.badge || b.slug,
            level: b.level || b.tier || null,
            category: b.category || null,
          })
  }
  const out = []
  for (const [key, value] of Object.entries(badges)) {
    if (key === 'total') continue
    if (Array.isArray(value)) {
      for (const b of value) {
        out.push(typeof b === 'string'
          ? { name: b, level: null, category: key }
          : { name: b.name || b.badge || b.slug, level: b.level || b.tier || null, category: key })
      }
    } else if (typeof value === 'string' || typeof value === 'number') {
      out.push({ name: key, level: String(value) })
    } else if (value && typeof value === 'object') {
      out.push({ name: value.name || key, level: value.level || value.tier || null, category: key })
    }
  }
  return out.filter((b) => b.name)
}

export default function LeaguePlayerPage() {
  const { name } = useParams()
  const { user, loading: authLoading } = useAuth()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await league.getPlayerCard(name))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [name])

  useEffect(() => {
    if (!authLoading && user) load()
    else if (!authLoading) setLoading(false)
  }, [authLoading, user, load])

  if (authLoading || loading) {
    return <Shell><p className="lg-muted">Loading…</p></Shell>
  }
  if (!user) {
    return (
      <Shell>
        <div className="lg-gate">
          <h1>League Portal</h1>
          <p>Sign in to see player ratings, badges and trade history.</p>
          <LeagueLoginButton />
        </div>
      </Shell>
    )
  }
  if (error) {
    return (
      <Shell>
        <p className="lg-error">{error}</p>
        <Link className="lg-back" to="/league">← Back to the league</Link>
      </Shell>
    )
  }

  const { player, ratings, history } = data
  const badges = normalizeBadges(ratings && ratings.badges)
  const attributes = (ratings && ratings.attributes) || {}
  const hasAttributes = Object.keys(attributes).length > 0

  return (
    <Shell>
      <Link className="lg-back" to="/league">← Back to the league</Link>

      <header className="lg-playerhead">
        {/* Headshots are hotlinked from 2kratings.com. If one fails, drop the
            element rather than leave an empty bordered box on the card. */}
        {ratings && ratings.player_image && (
          <img
            className="lg-playerimg"
            src={ratings.player_image}
            alt=""
            loading="lazy"
            onError={(e) => { e.currentTarget.style.display = 'none' }}
          />
        )}
        <div className="lg-playerid">
          <h1>{player.name}</h1>
          <p className="lg-playermeta">
            {player.is_free_agent ? 'Free agent' : player.team}
            {player.position ? ` · ${player.position}` : ''}
            {ratings && ratings.archetype ? ` · ${ratings.archetype}` : ''}
          </p>
          {ratings && (
            <p className="lg-playerbio">
              {[ratings.height, ratings.weight, ratings.wingspan && `${ratings.wingspan} wingspan`, ratings.college]
                .filter(Boolean).join(' · ')}
            </p>
          )}
        </div>
        {ratings && ratings.overall != null && (
          <div className="lg-ovr">
            <span className="lg-ovrnum">{ratings.overall}</span>
            <span className="lg-ovrlab">{ratings.game_version || '2K'} OVR</span>
          </div>
        )}
      </header>

      {!ratings && (
        <p className="lg-notice">
          No 2K ratings for this player yet. A commissioner can pull them with the ratings sync.
        </p>
      )}

      {hasAttributes && (
        <section>
          <h2 className="lg-subhead">Attributes</h2>
          <div className="lg-attrgroups">
            {GROUPS.map(([groupName, keys]) => {
              const present = keys.filter((k) => attributes[k] != null)
              if (!present.length) return null
              return (
                <div className="lg-attrgroup" key={groupName}>
                  <h3>{groupName}</h3>
                  <ul>
                    {present.map((k) => (
                      <li key={k}>
                        <span className="lg-attrname">{LABELS[k] || k}</span>
                        <span className="lg-attrbar">
                          <span className={`lg-attrfill is-${tier(attributes[k])}`}
                            style={{ width: `${Math.min(100, attributes[k])}%` }} />
                        </span>
                        <span className={`lg-attrval is-${tier(attributes[k])}`}>{attributes[k]}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )
            })}
          </div>
        </section>
      )}

      <section>
        <h2 className="lg-subhead">Badges</h2>
        {badges.length > 0 ? (
          <div className="lg-badgetiers">
            {['Legend', 'Hall of Fame', 'Gold', 'Silver', 'Bronze'].map((level) => {
              const group = badges.filter((b) => b.level === level)
              if (!group.length) return null
              return (
                <div className="lg-badgetier" key={level}>
                  <h3 className={`lg-tierlabel is-${tierClass(level)}`}>
                    {level} <span>{group.length}</span>
                  </h3>
                  <ul className="lg-badges">
                    {group.map((b, i) => (
                      <li key={`${b.name}-${i}`} className={`lg-badgechip is-${tierClass(level)}`}>
                        <span>{b.name}</span>
                        {b.category && <em>{b.category}</em>}
                      </li>
                    ))}
                  </ul>
                </div>
              )
            })}
          </div>
        ) : (
          <p className="lg-muted">
            Badges aren’t pulled yet. They only come from the per-player endpoint, which needs
            the nba2kapi key — a commissioner can run the badge sync once it’s set.
          </p>
        )}
      </section>

      {ratings && ratings.rating_history && ratings.rating_history.length > 0 && (
        <section>
          <h2 className="lg-subhead">Rating by game</h2>
          <ul className="lg-ratinghistory">
            {ratings.rating_history.map((h, i) => (
              <li key={`${h.gameVersion}-${i}`}>
                <span className="lg-hgame">{h.gameVersion}</span>
                <span className="lg-hovr">{h.overall}</span>
                {h.delta != null && h.delta !== 0 && (
                  <span className={`lg-hdelta ${h.delta > 0 ? 'is-up' : 'is-down'}`}>
                    {h.delta > 0 ? '+' : ''}{h.delta}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2 className="lg-subhead">League history</h2>
        {history.length === 0 ? (
          <p className="lg-muted">Hasn’t moved since the rosters were imported.</p>
        ) : (
          <ul className="lg-activity">
            {history.map((t) => (
              <li key={t.id}>
                <span className="lg-kind">{t.kind.toLowerCase()}</span>
                <span className="lg-move">
                  {t.from_team && t.to_team && <>{t.from_team} → {t.to_team}</>}
                  {t.from_team && !t.to_team && <>released by {t.from_team}</>}
                  {!t.from_team && t.to_team && <>signed by {t.to_team}</>}
                </span>
                {t.trade_ref && <span className="lg-ref">{t.trade_ref}</span>}
                <span className="lg-when">
                  {t.created_at ? new Date(`${t.created_at}Z`).toLocaleDateString() : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {ratings && ratings.synced_at && (
        <p className="lg-fineprint lg-muted">
          Ratings from nba2kapi.com, last synced {new Date(`${ratings.synced_at}Z`).toLocaleString()}.
        </p>
      )}
    </Shell>
  )
}

function Shell({ children }) {
  return (
    <div className="league-page">
      <div className="lg-shell">{children}</div>
    </div>
  )
}
