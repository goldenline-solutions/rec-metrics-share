// API utility functions for communicating with the Flask backend

/**
 * Get the base API URL based on environment
 * In dev mode: uses http://localhost:5000
 * In production: uses VITE_API_BASE_URL env var if set, otherwise uses relative URLs
 * @returns {string} Base API URL (with trailing slash removed)
 */
function getApiBaseUrl() {
  // Check if we're in development mode (Vite's built-in variable)
  if (import.meta.env.DEV) {
    return 'http://localhost:5000'
  }
  
  // In production, check for environment variable
  const prodUrl = import.meta.env.VITE_API_BASE_URL
  if (prodUrl) {
    // Remove trailing slash if present
    return prodUrl.replace(/\/$/, '')
  }
  
  // Default to relative URLs (same origin) for production
  return ''
}

/**
 * Build an API URL for the current environment
 * @param {string} path - API path (e.g., '/api/health' or 'api/health')
 * @returns {string} Full API URL
 */
export function apiUrl(path) {
  const baseUrl = getApiBaseUrl()
  
  // Ensure path starts with /api/
  if (!path.startsWith('/')) {
    path = '/' + path
  }
  if (!path.startsWith('/api/')) {
    path = '/api' + (path.startsWith('/') ? path : '/' + path)
  }
  
  // Combine base URL with path
  return baseUrl + path
}

/**
 * Upload a screenshot file to the backend for ingestion
 * @param {File} file - The image file to upload
 * @param {string} seasonLabel - Optional season label
 * @param {string} modeLabel - Optional mode label
 * @returns {Promise<Object>} The response from the backend
 */
export async function ingestScreenshot(file, seasonLabel = null, modeLabel = null) {
  const formData = new FormData()
  formData.append('screenshot', file)
  
  if (seasonLabel) {
    formData.append('season_label', seasonLabel)
  }
  
  if (modeLabel) {
    formData.append('mode_label', modeLabel)
  }
  
  const response = await fetch(apiUrl('/api/ingest'), {
    method: 'POST',
    body: formData,
    credentials: 'include' // Include cookies for authenticated requests
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Fetch list of games (paginated).
 * @param {string} filter - Filter type: 'all', 'needs_verification', 'incomplete_data'
 * @param {string} sort - Sort type: 'date_desc', 'date_asc', 'needs_verification_first'
 * @param {number} page - Page number (1-based, default 1)
 * @param {string} platform - Platform filter: 'all', 'PC', 'Console'
 * @param {string} gameVersion - NBA 2K title: '2K26', '2K27', or 'all'
 * @returns {Promise<{ games: Array, total: number, page: number, per_page: number, total_pages: number }>}
 */
export async function fetchGames(filter = 'all', sort = 'date_desc', page = 1, platform = 'all', gameVersion = null) {
  const params = new URLSearchParams()
  if (gameVersion) {
    params.append('game_version', gameVersion)
  }
  if (filter !== 'all') {
    params.append('filter', filter)
  }
  if (sort !== 'date_desc') {
    params.append('sort', sort)
  }
  if (platform !== 'all') {
    params.append('platform', platform)
  }
  if (page > 1) {
    params.append('page', String(page))
  }
  
  const url = apiUrl(`/api/games${params.toString() ? '?' + params.toString() : ''}`)
  const response = await fetch(url, {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Fetch detailed game information by ID
 * @param {string} gameId - The game ID
 * @returns {Promise<Object>} Game details object
 */
export async function fetchGameDetails(gameId) {
  const response = await fetch(apiUrl(`/api/games/${gameId}`), {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Get player name suggestions for autocomplete (partial match, case-insensitive).
 * @param {string} query - Search string
 * @param {number} limit - Max suggestions (default 10, max 20)
 * @param {AbortSignal} [signal] - Optional abort signal to cancel the request
 * @returns {Promise<{ suggestions: Array<{ gamertag: string }> }>}
 */
export async function getPlayerSuggestions(query, limit = 10, signal = null) {
  if (!query || !String(query).trim()) {
    return { suggestions: [] }
  }
  const params = new URLSearchParams({ q: String(query).trim(), limit: String(Math.min(limit, 20)) })
  const response = await fetch(apiUrl(`/api/players/suggest?${params}`), {
    credentials: 'include',
    signal: signal || undefined
  })
  if (!response.ok) {
    const err = await response.json()
    throw new Error(err.error || `HTTP ${response.status}`)
  }
  return await response.json()
}

/**
 * Search for a player by gamertag and get their stats
 * @param {string} query - The gamertag to search for
 * @param {string} platform - Filter by platform ('PC', 'Console') or 'ALL' (default: 'ALL')
 * @param {number} page - 1-based page number for games list (default: 1)
 * @param {number} perPage - Games per page (default: 25)
 * @param {string} gameVersion - NBA 2K title: '2K26', '2K27', or 'all'
 * @returns {Promise<Object>} Player stats and paginated games (games, total_games, page, per_page, total_pages)
 */
export async function searchPlayer(query, platform = 'ALL', page = 1, perPage = 25, gameVersion = null) {
  const params = new URLSearchParams({ q: query })
  if (platform !== 'ALL') params.set('platform', platform)
  if (gameVersion) params.set('game_version', gameVersion)
  params.set('page', String(page))
  params.set('per_page', String(perPage))
  const url = apiUrl(`/api/players/search?${params.toString()}`)
  const response = await fetch(url, {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Get leaderboard data for a specific statistic
 * @param {string} stat - The statistic to rank by (pts, reb, ast, etc.)
 * @param {number} limit - Number of players to return (default: 20)
 * @param {number} minGames - Minimum games played (default: 5)
 * @param {string} position - Filter by position (PG, SG, SF, PF, C) or 'ALL' (default: 'ALL')
 * @param {string} platform - Filter by platform ('PC', 'Console') or 'ALL' (default: 'ALL')
 * @param {string} gameVersion - NBA 2K title: '2K26', '2K27', or 'all'
 * @returns {Promise<Object>} Leaderboard data
 */
export async function getLeaderboard(stat = 'pts', limit = 20, minGames = 10, position = 'ALL', platform = 'ALL', gameVersion = null) {
  const params = new URLSearchParams({
    stat,
    limit: String(limit),
    min_games: String(minGames),
    position,
    platform
  })
  if (gameVersion) params.set('game_version', gameVersion)
  const url = apiUrl(`/api/leaderboard?${params.toString()}`)
  const response = await fetch(url, {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Get Rec Impact Rating (RIR) for all players
 * @param {number} minGames - Minimum games played to be included (default: 5)
 * @returns {Promise<Object>} RIR data with ratings and component breakdowns
 */
export async function getRecImpactRating(minGames = 10) {
  const response = await fetch(apiUrl(`/api/analytics/rec-impact-rating?min_games=${minGames}`), {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Get efficiency analytics for all players
 * @param {number} minGames - Minimum games played to be included (default: 5)
 * @returns {Promise<Object>} Analytics data with efficiency metrics
 */
export async function getEfficiencyAnalytics(minGames = 10) {
  const response = await fetch(apiUrl(`/api/analytics/efficiency?min_games=${minGames}`), {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Get site stats for landing page (games and players counts).
 * @returns {Promise<{ games_tracked: number, players_tracked: number }>}
 */
export async function getSiteStats() {
  const response = await fetch(apiUrl('/api/stats'), {
    credentials: 'include'
  })
  if (!response.ok) {
    const err = await response.json()
    throw new Error(err.error || `HTTP ${response.status}`)
  }
  return await response.json()
}

/**
 * Health check endpoint
 * @returns {Promise<Object>} Health status and version info
 */
export async function checkHealth() {
  const response = await fetch(apiUrl('/api/health'), {
    credentials: 'include'
  })
  
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status} ${response.statusText}`)
  }
  
  return await response.json()
}

/**
 * Get current authenticated user's profile
 * @returns {Promise<Object>} User profile data with roles and permissions
 */
export async function getCurrentUser() {
  const response = await fetch(apiUrl('/api/me'), {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Check if user has a specific role
 * @param {Object} user - User object from getCurrentUser()
 * @param {string} role - Role name to check
 * @returns {boolean}
 */
export function hasRole(user, role) {
  return user && user.roles && Array.isArray(user.roles) && user.roles.includes(role)
}

/**
 * Check if user has a specific permission
 * @param {Object} user - User object from getCurrentUser()
 * @param {string} permission - Permission name to check
 * @returns {boolean}
 */
export function hasPermission(user, permission) {
  return user && user.permissions && Array.isArray(user.permissions) && user.permissions.includes(permission)
}

/**
 * Update game data (admin only)
 * @param {string} gameId - The game ID
 * @param {Object} gameData - The game data to update
 * @returns {Promise<Object>} Updated game details
 */
export async function updateGame(gameId, gameData) {
  const response = await fetch(apiUrl(`/api/games/${gameId}`), {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json'
    },
    credentials: 'include',
    body: JSON.stringify(gameData)
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Clear warnings for a game (admin only)
 * @param {string} gameId - The game ID
 * @returns {Promise<Object>} Success message
 */
export async function clearGameWarnings(gameId) {
  const response = await fetch(apiUrl(`/api/games/${gameId}/clear-warnings`), {
    method: 'POST',
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Delete a game (admin only)
 * @param {string} gameId - The game ID
 * @returns {Promise<Object>} Success message
 */
export async function deleteGame(gameId) {
  const response = await fetch(apiUrl(`/api/games/${gameId}`), {
    method: 'DELETE',
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Get player profile with insights, trends, and shareable stat card
 * @param {string} username - Player gamertag
 * @param {string} gameVersion - NBA 2K title: '2K26', '2K27', or 'all'
 * @returns {Promise<Object>} Player profile data
 */
export async function getPlayerProfile(username, gameVersion = null) {
  const params = new URLSearchParams()
  if (gameVersion) params.set('game_version', gameVersion)
  const suffix = params.toString() ? `?${params.toString()}` : ''
  const response = await fetch(apiUrl(`/api/players/${encodeURIComponent(username)}/profile${suffix}`), {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Get a player's squad chemistry — teammates they win with and rivals they
 * play against most, derived from recorded game lineups.
 * @param {string} username - Player gamertag
 * @param {number} limit - max teammates/rivals (default 20)
 * @returns {Promise<{username, gamesAnalyzed, teammates: [], rivals: []}>}
 */
export async function getPlayerChemistry(username, limit = 20) {
  const response = await fetch(
    apiUrl(`/api/players/${encodeURIComponent(username)}/chemistry?limit=${limit}`),
    { credentials: 'include' }
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  return await response.json()
}

// AI Analysis - Commented out for now
/**
 * Get AI-powered performance analysis for a player
 * @param {string} username - Player username (gamertag)
 * @param {number} lastN - Optional number of recent games to analyze (default: 25)
 * @returns {Promise<Object>} Analysis data with strengths, weaknesses, coaching plan, etc.
 */
// export async function getPlayerAnalysis(username, lastN = 25) {
//   const params = new URLSearchParams()
//   if (lastN) {
//     params.append('last_n', lastN.toString())
//   }
//   
//   const url = apiUrl(`/api/players/${encodeURIComponent(username)}/analysis${params.toString() ? '?' + params.toString() : ''}`)
//   const response = await fetch(url, {
//     credentials: 'include'
//   })
//   
//   if (!response.ok) {
//     const error = await response.json()
//     throw new Error(error.error || `HTTP error! status: ${response.status}`)
//   }
//   
//   return await response.json()
// }

/**
 * Get all claims for the current user
 * @returns {Promise<Array>} Array of claim objects
 */
export async function getMyClaims() {
  const response = await fetch(apiUrl('/api/me/claims'), {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Create a new name claim
 * @param {string} displayName - Display name for the claim
 * @param {number} playerId - Optional existing player identity ID
 * @returns {Promise<Object>} Created claim object
 */
export async function createClaim(displayName, playerId = null) {
  const response = await fetch(apiUrl('/api/claims'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    credentials: 'include',
    body: JSON.stringify({
      display_name: displayName,
      player_id: playerId
    })
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Request verification for a claim
 * @param {number} claimId - Claim ID
 * @returns {Promise<Object>} Success message
 */
export async function requestVerification(claimId) {
  const response = await fetch(apiUrl(`/api/claims/${claimId}/request-verification`), {
    method: 'POST',
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Get unresolved games for the current user
 * @returns {Promise<Array>} Array of unresolved game player records
 */
export async function getUnresolvedGames() {
  const response = await fetch(apiUrl('/api/me/unresolved-games'), {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Confirm or reject a game player as belonging to the current user
 * @param {string} gameId - Game ID
 * @param {string} gamePlayerId - GamePlayer ID
 * @param {string} action - "me" or "not_me"
 * @param {number} claimId - Optional claim ID
 * @returns {Promise<Object>} Success message
 */
export async function confirmGamePlayer(gameId, gamePlayerId, action, claimId = null) {
  const response = await fetch(apiUrl(`/api/games/${gameId}/players/${gamePlayerId}/confirm`), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    credentials: 'include',
    body: JSON.stringify({
      action: action,
      claim_id: claimId
    })
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Ingest a build sheet screenshot
 * @param {File} file - The image file to upload
 * @param {string} targetUserId - Optional target user ID (admin only)
 * @param {boolean} isPublic - Whether build should be public (default false/private)
 * @returns {Promise<Object>} The build object with attributes
 */
export async function ingestBuildSheet(file, targetUserId = null, isPublic = false) {
  const formData = new FormData()
  formData.append('image', file)
  formData.append('is_public', isPublic ? 'true' : 'false')
  
  if (targetUserId) {
    formData.append('target_user_id', targetUserId)
  }
  
  const response = await fetch(apiUrl('/api/builds/ingest'), {
    method: 'POST',
    body: formData,
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Create a build from structured planner data (no screenshot).
 * @param {Object} buildData - { display_name, position, archetype, height, wingspan,
 *   weight_lbs, overall_current, overall_max, is_public, attributes: [...] }
 * @returns {Promise<Object>} The created build object
 */
export async function createBuild(buildData) {
  const response = await fetch(apiUrl('/api/builds/create'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(buildData)
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }

  return await response.json()
}

/**
 * Get builds for a player by username (public endpoint, no auth required)
 * @param {string} username - Player username
 * @returns {Promise<Array>} Array of build objects
 */
export async function getBuildsByUsername(username) {
  const response = await fetch(apiUrl(`/api/players/${encodeURIComponent(username)}/builds`), {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Get builds for a user
 * @param {string} userId - Optional user ID (admin only, defaults to current user)
 * @returns {Promise<Array>} Array of build objects
 */
export async function getBuilds(userId = null) {
  const params = new URLSearchParams()
  if (userId) {
    params.append('user_id', userId)
  }
  
  const url = apiUrl(`/api/builds${params.toString() ? '?' + params.toString() : ''}`)
  const response = await fetch(url, {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Get the admin-flagged template builds shown in the template gallery.
 * Requires login (the gallery is gated like the planner).
 * @returns {Promise<{ builds: Array }>}
 */
export async function getTemplateBuilds() {
  const response = await fetch(apiUrl('/api/builds/templates'), {
    credentials: 'include'
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }

  return await response.json()
}

/**
 * Get public builds feed with top attributes and usage stats.
 * @param {number} page - 1-based page number
 * @param {number} perPage - page size
 * @returns {Promise<{ builds: Array, total: number, page: number, per_page: number, total_pages: number }>}
 */
export async function getPublicBuilds(page = 1, perPage = 24) {
  const params = new URLSearchParams()
  params.set('page', String(page))
  params.set('per_page', String(perPage))

  const response = await fetch(apiUrl(`/api/builds/public?${params.toString()}`), {
    credentials: 'include'
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }

  return await response.json()
}

/**
 * Get a build by ID (public access allowed for builds from verified claims)
 * @param {number} buildId - Build ID
 * @returns {Promise<Object>} Build object with attributes
 */
export async function getBuild(buildId) {
  const response = await fetch(apiUrl(`/api/builds/${buildId}`), {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Get build usage summary and full game stat breakdown.
 * @param {number} buildId - Build ID
 * @returns {Promise<Object>} Usage object with averages and games array
 */
export async function getBuildUsage(buildId) {
  const response = await fetch(apiUrl(`/api/builds/${buildId}/usage`), {
    credentials: 'include'
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }

  return await response.json()
}

/**
 * Get vote totals and current user vote for a build.
 * @param {number} buildId - Build ID
 * @returns {Promise<{build_id:number, upvotes:number, downvotes:number, user_vote:'up'|'down'|null}>}
 */
export async function getBuildVotes(buildId) {
  const response = await fetch(apiUrl(`/api/builds/${buildId}/votes`), {
    credentials: 'include'
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }

  return await response.json()
}

/**
 * Set or clear current user's vote on a build.
 * @param {number} buildId - Build ID
 * @param {'up'|'down'|null} vote - Vote value or null to clear
 * @returns {Promise<{build_id:number, upvotes:number, downvotes:number, user_vote:'up'|'down'|null}>}
 */
export async function voteBuild(buildId, vote) {
  const response = await fetch(apiUrl(`/api/builds/${buildId}/vote`), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    credentials: 'include',
    body: JSON.stringify({ vote })
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }

  return await response.json()
}

/**
 * Update a build
 * @param {number} buildId - Build ID
 * @param {Object} updates - Fields to update (display_name, position, archetype)
 * @returns {Promise<Object>} Updated build object
 */
export async function updateBuild(buildId, updates) {
  const response = await fetch(apiUrl(`/api/builds/${buildId}`), {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json'
    },
    credentials: 'include',
    body: JSON.stringify(updates)
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Delete a build
 * @param {number} buildId - Build ID
 * @returns {Promise<Object>} Success message
 */
export async function deleteBuild(buildId) {
  const response = await fetch(apiUrl(`/api/builds/${buildId}`), {
    method: 'DELETE',
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Assign a build to a game player row
 * @param {string} gameId - Game ID
 * @param {string} gamePlayerRowId - GamePlayer row ID
 * @param {number|null} buildId - Build ID to assign (null to clear)
 * @returns {Promise<Object>} Updated game player row
 */
/**
 * Find a user by username (admin only)
 * @param {string} username - Username to search for
 * @returns {Promise<Object>} User object with user_id, display_name, normalized_name
 */
export async function findUserByUsername(username) {
  const response = await fetch(apiUrl(`/api/users/find-by-username?username=${encodeURIComponent(username)}`), {
    credentials: 'include'
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

export async function assignBuildToGamePlayer(gameId, gamePlayerRowId, buildId) {
  const response = await fetch(apiUrl(`/api/games/${gameId}/players/${gamePlayerRowId}/build`), {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json'
    },
    credentials: 'include',
    body: JSON.stringify({
      build_id: buildId
    })
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}

/**
 * Update the current user's platform selection
 * @param {string} platform - 'PC' or 'Console'
 * @returns {Promise<Object>} Updated user object
 */
export async function updateUserPlatform(platform) {
  const response = await fetch(apiUrl('/api/me/platform'), {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json'
    },
    credentials: 'include',
    body: JSON.stringify({ platform })
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP error! status: ${response.status}`)
  }
  
  return await response.json()
}
