import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import * as league from '../utils/leagueApi'
import LeagueLoginButton from '../components/LeagueLoginButton'
import GameplanChangesTab from './league/GameplanChangesTab'
import FreeAgentsTab from './league/FreeAgentsTab'
import GameplanTab from './league/GameplanTab'
import RulesTab from './league/RulesTab'
import ScoresTab from './league/ScoresTab'
import StandingsTab from './league/StandingsTab'
import StatsTab from './league/StatsTab'
import './LeaguePage.css'

const TABS = [
  { id: 'rosters', label: 'Rosters' },
  { id: 'gameplan', label: 'Coaching' },
  { id: 'trades', label: 'Trades' },
  { id: 'freeagents', label: 'Free Agents' },
  { id: 'standings', label: 'Standings' },
  { id: 'scores', label: 'Scores' },
  { id: 'stats', label: 'Stats' },
  { id: 'activity', label: 'Activity' },
  { id: 'rules', label: 'Rules' },
  { id: 'changes', label: 'Change in 2K', commishOnly: true },
]

const STATUS_TONE = {
  PENDING_GM: 'wait',
  PENDING_COMMISSIONER: 'wait',
  APPROVED_WINDOW: 'live',
  PROTESTED: 'alert',
  EXECUTED: 'done',
  DECLINED: 'dead',
  VETOED: 'dead',
  CANCELLED: 'dead',
  EXPIRED: 'dead',
  VOIDED: 'alert',
  OVERTURNED: 'dead',
}

// The API sends naive UTC timestamps ("2026-09-05T02:36:54"). Without a zone
// suffix the browser reads them as local time, which silently skews every
// countdown by the viewer's offset.
function utcDate(iso) {
  if (!iso) return null
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso)
  return new Date(hasZone ? iso : `${iso}Z`)
}

function timeLeft(iso) {
  if (!iso) return null
  const ms = utcDate(iso).getTime() - Date.now()
  if (ms <= 0) return 'any moment'
  const hours = Math.floor(ms / 3600000)
  if (hours >= 1) return `${hours}h left`
  return `${Math.max(1, Math.round(ms / 60000))}m left`
}

export default function LeaguePage() {
  const { user, loading: authLoading } = useAuth()
  const [membership, setMembership] = useState(null)
  const [teams, setTeams] = useState([])
  const [trades, setTrades] = useState([])
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('rosters')
  const [openTeamId, setOpenTeamId] = useState(null)
  const [roster, setRoster] = useState(null)
  const [busy, setBusy] = useState(null)
  const [flash, setFlash] = useState(null)
  const [changeCount, setChangeCount] = useState(0)

  const load = useCallback(async () => {
    setError(null)
    try {
      const me = await league.getMembership()
      setMembership(me)
      if (me.needs_choice || !me.is_member) {
        setLoading(false)
        return
      }
      const [teamData, tradeData, txnData] = await Promise.all([
        league.getTeams(),
        league.getTrades('open'),
        league.getTransactions(),
      ])
      setTeams(teamData.teams || [])
      setTrades(tradeData.trades || [])
      setTransactions(txnData.transactions || [])
      if (me.is_commissioner) {
        league.getGameplanChanges()
          .then((d) => setChangeCount((d.changes || []).length))
          .catch(() => {})
      }
      if (me.team) setOpenTeamId((current) => current || me.team.id)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!authLoading && user) load()
    else if (!authLoading) setLoading(false)
  }, [authLoading, user, load])

  useEffect(() => {
    if (!openTeamId) return
    let cancelled = false
    league
      .getRoster(openTeamId)
      .then((data) => { if (!cancelled) setRoster(data) })
      .catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [openTeamId])

  const act = async (label, fn) => {
    setBusy(label)
    setError(null)
    try {
      await fn()
      setFlash(label)
      setTimeout(() => setFlash(null), 3200)
      await load()
      if (openTeamId) setRoster(await league.getRoster(openTeamId))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  const myTeam = membership?.team
  const isCommish = membership?.is_commissioner

  const grouped = useMemo(() => {
    const east = teams.filter((t) => t.conference === 'East')
    const west = teams.filter((t) => t.conference === 'West')
    return [['Eastern Conference', east], ['Western Conference', west]]
  }, [teams])

  if (authLoading || loading) {
    return <div className="league-page"><div className="lg-shell"><p className="lg-muted">Loading the league…</p></div></div>
  }

  if (!user) {
    return (
      <div className="league-page">
        <div className="lg-shell lg-gate">
          <p className="lg-eyebrow">MyNBA League</p>
          <h1>League Portal</h1>
          <p>Rosters, trades and player cards for the league — sign in to get in.</p>
          <LeagueLoginButton />
          <p className="lg-muted lg-fineprint">
            Uses the same Discord account you use in the league server. GMs and
            commissioners get in automatically.
          </p>
        </div>
      </div>
    )
  }

  // Signed in, but in more than one league. Not an error — just undecided.
  if (membership && membership.needs_choice) {
    return (
      <div className="league-page">
        <div className="lg-shell lg-gate">
          <p className="lg-eyebrow">MyNBA</p>
          <h1>Which league?</h1>
          <p>You're in more than one. Pick the one you want to open.</p>
          <ul className="lg-leaguepick">
            {(membership.leagues || []).map((l) => (
              <li key={l.guild_id}>
                <button
                  type="button"
                  className="lg-btn lg-btn-go lg-btn-wide"
                  onClick={() => {
                    league.setSelectedLeague(l.guild_id)
                    setLoading(true)
                    load()
                  }}
                >
                  {l.name}
                </button>
              </li>
            ))}
          </ul>
          <p className="lg-muted lg-fineprint">You can switch at any time from the header.</p>
        </div>
      </div>
    )
  }

  // No league exists yet — a different problem from "you're not in it", and it
  // needs a setup step rather than a permission.
  if (membership && !membership.has_league) {
    return (
      <div className="league-page">
        <div className="lg-shell lg-gate">
          <h1>No league yet</h1>
          <p>Nobody has set up a MyNBA league on this site.</p>
          {membership.is_site_admin ? (
            <>
              <p>
                Run <code className="lg-code">/league-setup</code> in your Discord server. That
                creates the league, seeds all 30 teams, and makes you the first commissioner.
              </p>
              <p className="lg-muted">
                Then <code className="lg-code">/league-seed-rosters</code> fills it from the
                current 2K rosters, free agents included.
              </p>
            </>
          ) : (
            <p className="lg-muted">Ask a commissioner to run the league setup in Discord.</p>
          )}
        </div>
      </div>
    )
  }

  if (membership && !membership.is_member) {
    return (
      <div className="league-page">
        <div className="lg-shell lg-gate">
          <h1>League Portal</h1>
          <p>
            <strong>{membership.league?.name || 'The league'}</strong> is set up, but your account
            isn’t part of it.
          </p>
          <p className="lg-muted">
            Ask a commissioner to run <code className="lg-code">/team-set-gm</code> for your team,
            or <code className="lg-code">/league-commissioner</code> to add you as one.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="league-page">
      <div className="lg-shell">
        <header className="lg-head">
          <div>
            <p className="lg-eyebrow">{membership?.league?.name || 'MyNBA League'}</p>
            <h1>League Portal</h1>
          </div>
          <div className="lg-identity">
            {(membership?.leagues || []).length > 1 && (
              <select
                className="lg-leagueswitch"
                aria-label="Switch league"
                value={membership.league?.guild_id || ''}
                onChange={(e) => {
                  league.setSelectedLeague(e.target.value)
                  setRoster(null)
                  setOpenTeamId(null)
                  setLoading(true)
                  load()
                }}
              >
                {membership.leagues.map((l) => (
                  <option key={l.guild_id} value={l.guild_id}>{l.name}</option>
                ))}
              </select>
            )}
            {myTeam && <span className="lg-badge lg-badge-team">{myTeam.abbrev} · your team</span>}
            {isCommish && <span className="lg-badge lg-badge-commish">Commissioner</span>}
            {membership?.league?.roster_lock_message && (
              <span className="lg-badge lg-badge-locked" title={membership.league.roster_lock_message}>
                {membership.league.trades_locked ? 'Trading locked' : 'Rosters locked'}
              </span>
            )}
          </div>
        </header>

        {flash && <div className="lg-flash">{flash} — done.</div>}
        {error && <div className="lg-error">{error}</div>}

        <nav className="lg-tabs" role="tablist">
          {TABS.filter((t) => !t.commishOnly || isCommish).map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              className={`lg-tab${tab === t.id ? ' is-active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
              {t.id === 'trades' && trades.length > 0 && <span className="lg-count">{trades.length}</span>}
              {t.id === 'changes' && changeCount > 0 && <span className="lg-count">{changeCount}</span>}
            </button>
          ))}
        </nav>

        {tab === 'rosters' && (
          <RostersTab
            grouped={grouped}
            openTeamId={openTeamId}
            setOpenTeamId={setOpenTeamId}
            roster={roster}
            myTeamId={myTeam?.id}
          />
        )}

        {tab === 'trades' && (
          <TradesTab
            trades={trades}
            teams={teams}
            myTeam={myTeam}
            isCommish={isCommish}
            busy={busy}
            act={act}
            locked={membership?.league?.roster_lock_message || null}
            maxTeams={membership?.league?.max_trade_teams ?? 3}
          />
        )}

        {tab === 'gameplan' && (
          <GameplanTab
            teams={teams}
            myTeam={myTeam}
            isCommish={isCommish}
            onSaved={() => {
              if (isCommish) league.getGameplanChanges().then((d) => setChangeCount((d.changes || []).length)).catch(() => {})
            }}
          />
        )}

        {tab === 'activity' && <ActivityTab transactions={transactions} />}

        {tab === 'freeagents' && (
          <FreeAgentsTab
            teams={teams}
            myTeam={myTeam}
            isCommish={isCommish}
            locked={membership?.league?.roster_lock_message || null}
            rosterSize={membership?.league?.roster_size ?? 8}
            onSigned={load}
          />
        )}

        {tab === 'standings' && <StandingsTab myTeamId={myTeam?.id} />}

        {tab === 'scores' && <ScoresTab teams={teams} isCommish={isCommish} />}

        {tab === 'stats' && <StatsTab teams={teams} myTeamId={myTeam?.id} />}

        {tab === 'rules' && <RulesTab onSettingsSaved={load} />}

        {tab === 'changes' && isCommish && <GameplanChangesTab onCountChange={setChangeCount} />}
      </div>
    </div>
  )
}

function RostersTab({ grouped, openTeamId, setOpenTeamId, roster, myTeamId }) {
  return (
    <div className="lg-split">
      <div className="lg-teamlist">
        {grouped.map(([label, list]) => (
          <section key={label}>
            <h2 className="lg-subhead">{label}</h2>
            <ul className="lg-teams">
              {list.map((team) => (
                <li key={team.id}>
                  <button
                    className={`lg-teamrow${openTeamId === team.id ? ' is-open' : ''}${team.id === myTeamId ? ' is-mine' : ''}`}
                    onClick={() => setOpenTeamId(team.id)}
                  >
                    <span className="lg-abbrev">{team.abbrev}</span>
                    <span className="lg-teamname">{team.name}</span>
                    <span className="lg-gm">{team.is_cpu ? 'CPU' : team.gm_display_name || 'GM'}</span>
                    <span className={`lg-rostercount${team.roster_count !== team.roster_target ? ' is-off' : ''}`}>
                      {team.roster_count}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <div className="lg-roster">
        {!roster && <p className="lg-muted">Pick a team.</p>}
        {roster && (
          <>
            <div className="lg-rosterhead">
              <h2>{roster.team.full_name || roster.team.name}</h2>
              <p className="lg-muted">
                {roster.players.length} players
                {roster.team.roster_target ? ` · target ${roster.team.roster_target}` : ''}
                {roster.team.is_cpu ? ' · CPU team' : roster.team.gm_display_name ? ` · GM ${roster.team.gm_display_name}` : ''}
              </p>
            </div>
            {roster.players.length === 0 ? (
              <p className="lg-muted">No players imported for this team yet.</p>
            ) : (
              <div className="lg-tablewrap">
                <table className="lg-table">
                  <thead>
                    <tr><th>Player</th><th>Pos</th><th className="num">OVR</th><th className="num">Age</th></tr>
                  </thead>
                  <tbody>
                    {roster.players.map((p) => (
                      <tr key={p.id}>
                        <td>
                          <Link className="lg-playerlink" to={`/league/player/${encodeURIComponent(p.name)}`}>
                            {p.name}
                          </Link>
                        </td>
                        <td>{p.position || '—'}</td>
                        <td className="num">{p.ovr ?? '—'}</td>
                        <td className="num">{p.age ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function TradesTab({ trades, teams, myTeam, isCommish, busy, act, locked, maxTeams }) {
  return (
    <div className="lg-trades">
      {myTeam && !locked && <ProposeForm teams={teams} myTeam={myTeam} busy={busy} act={act} maxTeams={maxTeams} />}
      {locked && <p className="lg-notice">{locked} New proposals, accepts and signings open again after that.</p>}

      <h2 className="lg-subhead">Open trades</h2>
      {trades.length === 0 && <p className="lg-muted">Nothing pending.</p>}
      <ul className="lg-tradelist">
        {trades.map((t) => (
          <TradeCard key={t.id} trade={t} myTeam={myTeam} isCommish={isCommish} busy={busy} act={act} />
        ))}
      </ul>
    </div>
  )
}

function TradeCard({ trade, myTeam, isCommish, busy, act }) {
  const tone = STATUS_TONE[trade.status] || 'wait'
  const seats = trade.teams || []
  const threeWay = (trade.team_count || seats.length) > 2
  const mySeat = myTeam && seats.find((t) => t.id === myTeam.id)
  // Fall back to the named columns for trades recorded before seats existed.
  const mine = mySeat
    ? true
    : myTeam && (trade.proposer_team.id === myTeam.id || trade.counterparty_team.id === myTeam.id)
  const isProposer = myTeam && trade.proposer_team.id === myTeam.id
  // Anyone in the deal who has not answered yet can accept or decline.
  const isReceiver = mySeat
    ? !mySeat.is_proposer && !mySeat.accepted && !mySeat.declined
    : myTeam && trade.counterparty_team.id === myTeam.id

  return (
    <li className={`lg-trade lg-tone-${tone}${mine ? ' is-mine' : ''}`}>
      <div className="lg-tradetop">
        <span className="lg-ref">{trade.ref}</span>
        {threeWay && (
          <span className="lg-threeway">{seats.map((t) => t.abbrev).join(' / ')}</span>
        )}
        <span className={`lg-status lg-tone-${tone}`}>{trade.status_label}</span>
        {trade.execute_after && <span className="lg-muted">{timeLeft(trade.execute_after)}</span>}
      </div>

      {threeWay ? (
        <div className="lg-legs">
          {(trade.movement || []).map((side) => (
            <div className="lg-leg" key={side.team}>
              <p className="lg-sideteam">{side.team}</p>
              <ul>
                {side.sends.map((m) => (
                  <li key={`out-${m.player}`} className="lg-out">
                    {m.player} <span>→ {m.team}</span>
                  </li>
                ))}
                {side.gets.map((m) => (
                  <li key={`in-${m.player}`} className="lg-in">
                    {m.player} <span>← {m.team}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : (
        <div className="lg-swap">
          <div className="lg-side">
            <p className="lg-sideteam">{trade.proposer_team.name} send</p>
            <ul>{(trade.sending || []).map((n) => <li key={n}>{n}</li>)}
              {(trade.sending || []).length === 0 && <li className="lg-muted">nobody</li>}</ul>
          </div>
          <div className="lg-arrow" aria-hidden="true">⇄</div>
          <div className="lg-side">
            <p className="lg-sideteam">{trade.counterparty_team.name} send</p>
            <ul>{(trade.receiving || []).map((n) => <li key={n}>{n}</li>)}
              {(trade.receiving || []).length === 0 && <li className="lg-muted">nobody</li>}</ul>
          </div>
        </div>
      )}

      {(trade.teams || []).length > 0 && trade.status === 'PENDING_GM' && (
        <ul className="lg-signoff">
          {trade.teams.map((t) => (
            <li key={t.id} className={t.declined ? 'is-declined' : t.accepted ? 'is-accepted' : 'is-waiting'}>
              {t.declined ? '✕' : t.accepted ? '✓' : '·'} {t.name}
              {t.is_proposer ? ' (proposed)' : t.is_cpu ? ' (CPU)' : ''}
            </li>
          ))}
        </ul>
      )}

      {trade.note && <p className="lg-note">“{trade.note}”</p>}
      {trade.votes && (
        <p className="lg-muted">
          Vote: {trade.votes.uphold} to keep it, {trade.votes.overturn} to kill it
          {trade.votes.eligible ? ` · ${trade.votes.eligible} GMs eligible` : ''}
        </p>
      )}

      <div className="lg-actions">
        {trade.status === 'PENDING_GM' && isReceiver && (
          <>
            <button className="lg-btn lg-btn-go" disabled={!!busy}
              onClick={() => act(`Accepted ${trade.ref}`, () => league.acceptTrade(trade.ref))}>Accept</button>
            <button className="lg-btn" disabled={!!busy}
              onClick={() => act(`Declined ${trade.ref}`, () => league.declineTrade(trade.ref))}>Decline</button>
          </>
        )}
        {trade.status === 'PENDING_GM' && isProposer && (
          <button className="lg-btn" disabled={!!busy}
            onClick={() => act(`Withdrew ${trade.ref}`, () => league.cancelTrade(trade.ref))}>Withdraw</button>
        )}
        {trade.status === 'PENDING_COMMISSIONER' && isCommish && (
          <>
            <button className="lg-btn lg-btn-go" disabled={!!busy}
              onClick={() => act(`Approved ${trade.ref}`, () => league.approveTrade(trade.ref))}>Approve</button>
            <button className="lg-btn lg-btn-stop" disabled={!!busy}
              onClick={() => act(`Vetoed ${trade.ref}`, () => league.vetoTrade(trade.ref))}>Veto</button>
          </>
        )}
        {trade.status === 'APPROVED_WINDOW' && myTeam && !mine && (
          <button className="lg-btn lg-btn-stop" disabled={!!busy}
            onClick={() => act(`Protested ${trade.ref}`, () => league.protestTrade(trade.ref))}>Protest</button>
        )}
        {trade.status === 'APPROVED_WINDOW' && isCommish && (
          <button className="lg-btn lg-btn-go" disabled={!!busy}
            onClick={() => act(`Executed ${trade.ref}`, () => league.executeTradeNow(trade.ref))}>
            Execute now
          </button>
        )}
        {trade.status === 'PROTESTED' && myTeam && !mine && (
          <>
            <button className="lg-btn lg-btn-go" disabled={!!busy}
              onClick={() => act(`Voted to keep ${trade.ref}`, () => league.voteOnTrade(trade.ref, true))}>Let it stand</button>
            <button className="lg-btn lg-btn-stop" disabled={!!busy}
              onClick={() => act(`Voted to kill ${trade.ref}`, () => league.voteOnTrade(trade.ref, false))}>Overturn</button>
          </>
        )}
        {trade.status === 'PROTESTED' && isCommish && (
          <button className="lg-btn" disabled={!!busy}
            onClick={() => act(`Closed the vote on ${trade.ref}`, () => league.resolveProtest(trade.ref))}>Close the vote</button>
        )}
      </div>
    </li>
  )
}

function ProposeForm({ teams, myTeam, busy, act, maxTeams = 3 }) {
  const [partnerIds, setPartnerIds] = useState([''])
  const [note, setNote] = useState('')
  const [rosters, setRosters] = useState({})
  // destinations[playerName] = team id he is going to
  const [destinations, setDestinations] = useState({})

  const others = teams.filter((t) => t.id !== myTeam.id)
  const chosen = partnerIds.filter(Boolean)
  const involved = [myTeam.id, ...chosen]
  const threeWay = chosen.length > 1

  useEffect(() => {
    let cancelled = false
    Promise.all(involved.map((id) => league.getRoster(id).then((d) => [id, d.players || []])))
      .then((pairs) => { if (!cancelled) setRosters(Object.fromEntries(pairs)) })
      .catch(() => { if (!cancelled) setRosters({}) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [involved.join(',')])

  // Drop any pick whose team left the trade.
  useEffect(() => {
    setDestinations((current) => {
      const valid = {}
      for (const [player, toId] of Object.entries(current)) {
        const owner = Object.entries(rosters).find(([, list]) => list.some((p) => p.name === player))
        if (owner && involved.includes(owner[0]) && involved.includes(toId)) valid[player] = toId
      }
      return valid
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [involved.join(','), rosters])

  const teamName = (id) => teams.find((t) => t.id === id)?.name || ''

  const setDestination = (playerName, toId) =>
    setDestinations((current) => {
      const next = { ...current }
      if (!toId) delete next[playerName]
      else next[playerName] = toId
      return next
    })

  const picked = Object.entries(destinations)
  const ready = chosen.length >= 1 && picked.length > 0

  const submit = (e) => {
    e.preventDefault()
    const label = threeWay
      ? `Proposed a ${involved.length}-team trade`
      : `Proposed a trade to the ${teamName(chosen[0])}`
    act(label, async () => {
      await league.proposeMoves({
        moves: picked.map(([player, toId]) => ({ player, to: teamName(toId) })),
        note: note || null,
      })
      setDestinations({})
      setNote('')
      setPartnerIds([''])
    })
  }

  return (
    <form className="lg-propose" onSubmit={submit}>
      <h2 className="lg-subhead">Propose a trade</h2>

      <div className="lg-partners">
        {partnerIds.map((id, i) => (
          <label className="lg-field" key={i}>
            <span>{i === 0 ? 'Trade with' : 'And'}</span>
            <select
              value={id}
              onChange={(e) => {
                const next = [...partnerIds]
                next[i] = e.target.value
                setPartnerIds(next.filter((v, idx) => v || idx === 0 || idx < next.length - 1))
              }}
            >
              <option value="">Pick a team…</option>
              {others
                .filter((t) => t.id === id || !partnerIds.includes(t.id))
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}{t.is_cpu ? ' (CPU)' : ''}
                  </option>
                ))}
            </select>
          </label>
        ))}

        {partnerIds.length < 2 && partnerIds[0] && maxTeams >= 3 && (
          <button type="button" className="lg-btn lg-addteam" onClick={() => setPartnerIds([...partnerIds, ''])}>
            + Add a third team
          </button>
        )}
        {partnerIds.length > 1 && (
          <button type="button" className="lg-btn lg-addteam" onClick={() => setPartnerIds([partnerIds[0]])}>
            − Back to two teams
          </button>
        )}
      </div>

      <p className="lg-muted lg-fineprint">
        {threeWay
          ? 'Pick who each player goes to. A player can go to any team in the deal.'
          : 'Tick a player to send him the other way.'}
      </p>

      <div className={`lg-picker${threeWay ? ' is-wide' : ''}`}>
        {involved.map((teamId) => (
          <div key={teamId}>
            <p className="lg-pickhead">
              {teamId === myTeam.id ? `${teamName(teamId)} (you)` : teamName(teamId)}
            </p>
            <MovePicker
              players={rosters[teamId] || []}
              destinations={destinations}
              options={involved.filter((id) => id !== teamId).map((id) => ({ id, name: teamName(id) }))}
              onChange={setDestination}
            />
          </div>
        ))}
      </div>

      <label className="lg-field">
        <span>Note (optional)</span>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why this works for everyone" />
      </label>

      <button className="lg-btn lg-btn-go lg-btn-wide" type="submit" disabled={!ready || !!busy}>
        {busy ? 'Sending…' : `Send proposal${picked.length ? ` (${picked.length} player${picked.length === 1 ? '' : 's'})` : ''}`}
      </button>
      <p className="lg-muted lg-fineprint">
        Every team in the deal has to accept, then a commissioner approves. Rosters only change after that.
      </p>
    </form>
  )
}

function MovePicker({ players, destinations, options, onChange }) {
  if (!players.length) return <p className="lg-muted">No players.</p>
  return (
    <ul className="lg-picklist">
      {players.map((p) => {
        const to = destinations[p.name] || ''
        return (
          <li key={p.id}>
            <label className={to ? 'is-picked' : ''}>
              <input
                type="checkbox"
                checked={!!to}
                onChange={() => onChange(p.name, to ? '' : options[0]?.id || '')}
              />
              <span className="lg-pickname">{p.name}</span>
              <span className="lg-pickmeta">{p.position || '—'} {p.ovr ? `· ${p.ovr}` : ''}</span>
            </label>
            {to && options.length > 1 && (
              <select
                className="lg-dest"
                value={to}
                onChange={(e) => onChange(p.name, e.target.value)}
                aria-label={`Where does ${p.name} go?`}
              >
                {options.map((o) => (
                  <option key={o.id} value={o.id}>→ {o.name}</option>
                ))}
              </select>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function PlayerPicker({ players, selected, onToggle }) {
  if (!players.length) return <p className="lg-muted">No players.</p>
  return (
    <ul className="lg-picklist">
      {players.map((p) => (
        <li key={p.id}>
          <label className={selected.includes(p.name) ? 'is-picked' : ''}>
            <input type="checkbox" checked={selected.includes(p.name)} onChange={() => onToggle(p.name)} />
            <span className="lg-pickname">{p.name}</span>
            <span className="lg-pickmeta">{p.position || '—'} {p.ovr ? `· ${p.ovr}` : ''}</span>
          </label>
        </li>
      ))}
    </ul>
  )
}

function ActivityTab({ transactions }) {
  if (!transactions.length) return <p className="lg-muted">Nothing has happened yet.</p>
  return (
    <ul className="lg-activity">
      {transactions.map((t) => (
        <li key={t.id}>
          <span className="lg-kind">{t.kind.toLowerCase()}</span>
          <span className="lg-move">
            <strong>{t.player_name}</strong>
            {t.from_team && t.to_team && <> · {t.from_team} → {t.to_team}</>}
            {t.from_team && !t.to_team && <> · released by {t.from_team}</>}
            {!t.from_team && t.to_team && <> · signed by {t.to_team}</>}
          </span>
          {t.trade_ref && <span className="lg-ref">{t.trade_ref}</span>}
          <span className="lg-when">{t.created_at ? utcDate(t.created_at).toLocaleString() : ''}</span>
        </li>
      ))}
    </ul>
  )
}
