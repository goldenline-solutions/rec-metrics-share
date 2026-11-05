// MyNBA league portal API calls.
// Every endpoint is role-gated server-side; these helpers just surface the
// error message the backend wrote, which is already written for a human.

import { apiUrl } from './api'

const LEAGUE_KEY = 'mynba.guildId'

let selected = null

/**
 * Which league the portal is looking at.
 *
 * Every call carries it, because the server can no longer guess: once a second
 * league existed, "the only one" stopped being an answer.
 */
export function getSelectedLeague() {
  try {
    return window.localStorage.getItem(LEAGUE_KEY) || null
  } catch {
    return null
  }
}

export function setSelectedLeague(guildId) {
  try {
    if (guildId) window.localStorage.setItem(LEAGUE_KEY, guildId)
    else window.localStorage.removeItem(LEAGUE_KEY)
  } catch {
    /* private mode — the id still rides along for this page load */
  }
  selected = guildId || null
}

selected = getSelectedLeague()

function withLeague(path) {
  if (!selected) return path
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}guild_id=${encodeURIComponent(selected)}`
}

async function request(path, { method = 'GET', body } = {}) {
  const payload = body && selected ? { guild_id: selected, ...body } : body

  const response = await fetch(apiUrl(withLeague(path)), {
    method,
    credentials: 'include',
    headers: payload ? { 'Content-Type': 'application/json' } : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
  })

  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const err = new Error(data.error || `Request failed (${response.status})`)
    err.code = data.code
    err.status = response.status
    err.candidates = data.candidates
    err.leagues = data.leagues
    throw err
  }
  return data
}

/** Leagues this account can open. */
export const getMyLeagues = () => request('/api/mynba/leagues')

/** Who the signed-in user is inside the league: their team, and what they can do. */
export const getMembership = () => request('/api/mynba/me')

export const getTeams = () => request('/api/mynba/teams')

export const getRoster = (teamId) => request(`/api/mynba/teams/${teamId}/roster`)

export const getFreeAgents = (position) =>
  request(`/api/mynba/free-agents${position ? `?position=${encodeURIComponent(position)}` : ''}`)

export const getTrades = (status = 'open', limit = 50) =>
  request(`/api/mynba/trades?status=${encodeURIComponent(status)}&limit=${limit}`)

export const getTransactions = (limit = 60) =>
  request(`/api/mynba/transactions?limit=${limit}`)

/** Propose a two-team trade. `send`/`receive` are arrays of player names. */
export const proposeTrade = ({ withTeam, send, receive, note }) =>
  request('/api/mynba/trades', {
    method: 'POST',
    body: { with_team: withTeam, send, receive, note },
  })

/**
 * Propose a trade of any shape. `moves` is [{ player, to }] — the origin is
 * whichever team currently holds the player, so it never has to be stated.
 */
export const proposeMoves = ({ moves, note }) =>
  request('/api/mynba/trades', { method: 'POST', body: { moves, note } })

const tradeAction = (action) => (ref, body) =>
  request(`/api/mynba/trades/${encodeURIComponent(ref)}/${action}`, { method: 'POST', body })

export const acceptTrade = tradeAction('accept')
export const declineTrade = tradeAction('decline')
export const cancelTrade = tradeAction('cancel')
export const approveTrade = tradeAction('approve')
export const vetoTrade = tradeAction('veto')
export const protestTrade = tradeAction('protest')
/** Commissioner closes an open protest window early and applies the trade. */
export const executeTradeNow = tradeAction('execute')
export const voteOnTrade = (ref, uphold) => tradeAction('vote')(ref, { uphold })
export const resolveProtest = tradeAction('resolve-protest')

export const setTradeLock = (locked, reason) =>
  request('/api/mynba/league', {
    method: 'PATCH',
    body: { trades_locked: locked, trades_locked_reason: reason || null },
  })

/** League state + the full 2K card (attributes, badges, rating history) for one player. */
export const getPlayerCard = (name) =>
  request(`/api/mynba/players/${encodeURIComponent(name)}/card`)

/** How fresh the 2K reference data is, and whether badges have been pulled. */
export const getRatingsStatus = () => request('/api/mynba/ratings/status')

/** Commissioner: refresh ratings from nba2kapi. Touches no roster. */
export const syncRatings = (era = 'curr') =>
  request('/api/mynba/ratings/sync', { method: 'POST', body: { era } })

/** Commissioner: create league rosters from the 2K reference data (setup step). */
export const seedRosters = ({ era = 'curr', dryRun = false } = {}) =>
  request('/api/mynba/ratings/seed-rosters', {
    method: 'POST',
    body: { era, dry_run: dryRun },
  })

/** Mark or clear a player as untouchable (can't be traded). */
export const setUntouchable = (playerName, untouchable) =>
  request(`/api/mynba/players/${encodeURIComponent(playerName)}/untouchable`, {
    method: 'POST',
    body: { untouchable },
  })

/** Gameplan settings, their allowed 2K values, rotation rules, and the lock. */
export const getGameplanOptions = () => request('/api/mynba/gameplan/options')

/** Every team's current coaching settings (no rotations). */
export const getAllGameplans = () => request('/api/mynba/gameplans')

export const getTeamGameplan = (teamId) => request(`/api/mynba/teams/${teamId}/gameplan`)

/** Save settings and/or rotation. `baseVersion` stops two editors overwriting each other. */
export const saveTeamGameplan = (teamId, { settings, rotation, baseVersion }) =>
  request(`/api/mynba/teams/${teamId}/gameplan`, {
    method: 'PUT',
    body: { settings, rotation, base_version: baseVersion },
  })

/** Commissioner: what still has to be changed in 2K. */
export const getGameplanChanges = ({ includeDone = false } = {}) =>
  request(`/api/mynba/gameplan/changes${includeDone ? '?include_done=1' : ''}`)

export const markGameplanChanges = (ids, done = true) =>
  request('/api/mynba/gameplan/changes/mark', { method: 'POST', body: { ids, done } })

/** The rulebook (with numbers filled in) plus the league settings it describes. */
export const getRules = () => request('/api/mynba/rules')

/** Commissioner: replace the written rules. `rules` is [{ id?, title, body }]. */
export const saveRules = (rules, baseVersion) =>
  request('/api/mynba/rules', { method: 'PUT', body: { rules, base_version: baseVersion } })

/** Commissioner: change enforced league settings (roster size, minutes minimums, sim day…). */
export const updateLeagueSettings = (settings) =>
  request('/api/mynba/league', { method: 'PATCH', body: settings })

/** Commissioner: read one box-score screenshot. Returns game drafts; saves nothing. */
export async function readBoxScore(file) {
  const form = new FormData()
  form.append('files', file)
  const response = await fetch(apiUrl(withLeague('/api/mynba/games/read')), {
    method: 'POST',
    credentials: 'include',
    body: form,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || `Couldn't read ${file.name} (${response.status})`)
  return data
}

export const getGames = () => request('/api/mynba/games')

/** Commissioner: save a reviewed game (new when no id). */
export const saveGame = (game, { allowDuplicate = false } = {}) =>
  request(game.id ? `/api/mynba/games/${game.id}` : '/api/mynba/games', {
    method: game.id ? 'PUT' : 'POST',
    body: { ...game, allow_duplicate: allowDuplicate },
  })

export const deleteGame = (id) => request(`/api/mynba/games/${id}`, { method: 'DELETE' })

/** Standings by conference plus the award races, from saved games. */
export const getStandings = () => request('/api/mynba/standings')

export const getLeagueStats = () => request('/api/mynba/stats')

/** Sign a free agent. `release` drops one of the team's players first; `team` is commissioner-only. */
export const signFreeAgent = (playerName, { team, release } = {}) =>
  request(`/api/mynba/players/${encodeURIComponent(playerName)}/sign`, {
    method: 'POST',
    body: { team: team || undefined, release: release || undefined },
  })
