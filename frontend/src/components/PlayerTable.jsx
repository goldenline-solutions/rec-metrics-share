import { useState, useEffect, useCallback } from 'react'
import { getBuilds, assignBuildToGamePlayer, hasRole, getBuild } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import { useVerifiedClaim } from '../hooks/useVerifiedClaim'
import './PlayerTable.css'

// Helper function to remove timestamp from build display name
const formatBuildName = (displayName) => {
  if (!displayName) return ''
  // Remove timestamp pattern: " - YYYY-MM-DDTHH:MM:SSZ" or similar ISO date formats
  const timestampPattern = /\s*-\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?/i
  return displayName.replace(timestampPattern, '').trim()
}

/**
 * PlayerTable component - displays player statistics in a table format
 * 
 * Props:
 * - players: array - array of player objects with stats
 * - gameId: string - game ID for build assignment
 * - isEditMode: boolean - whether we're in edit mode (allows editing builds)
 */
function PlayerTable({ players, gameId, isEditMode = false }) {
  const { user } = useAuth()
  const { verifiedClaim } = useVerifiedClaim()
  const [buildsByUser, setBuildsByUser] = useState({}) // Map of user_id -> builds array
  const [buildsById, setBuildsById] = useState({}) // Map of build_id -> build object (for read-only display)
  const [loadedUsers, setLoadedUsers] = useState(new Set()) // Track which users we've loaded builds for
  const [assigningBuild, setAssigningBuild] = useState({})

  // Check if user can assign build to a player row
  const canAssignBuild = (player) => {
    if (!user) return false
    if (hasRole(user, 'admin')) return true
    // Normal user: check if this row is their claimed username
    if (!verifiedClaim) return false
    const normalizedGamertag = (player.gamertag || '').toLowerCase().trim()
    const normalizedClaim = verifiedClaim.normalized_name?.toLowerCase().trim()
    return normalizedGamertag === normalizedClaim
  }

  // Check if build is editable for this row
  const isBuildEditable = (player) => {
    // Editable if in edit mode OR user has claimed this username
    return isEditMode || canAssignBuild(player)
  }

  // Load builds for each row's claim owner when players change
  useEffect(() => {
    if (!user || !players) return
    
    // Get unique claim owner user IDs from players
    const claimOwnerIds = new Set()
    players.forEach(player => {
      if (player.claim_owner_user_id) {
        claimOwnerIds.add(player.claim_owner_user_id)
      }
      // Also add current user's ID if they can assign to this row (fallback)
      if (canAssignBuild(player) && user.id) {
        claimOwnerIds.add(user.id)
      }
    })
    
    // Filter out users we've already loaded
    const usersToLoad = Array.from(claimOwnerIds).filter(userId => !loadedUsers.has(userId))
    
    if (usersToLoad.length === 0) return // All users already loaded
    
    // Mark as loading
    setLoadedUsers(prev => new Set([...prev, ...usersToLoad]))
    
    // Load builds for each claim owner
    Promise.all(
      usersToLoad.map(async (userId) => {
        try {
          const data = await getBuilds(userId)
          setBuildsByUser(prev => ({ ...prev, [userId]: data }))
          // Also index by build ID for quick lookup
          const buildsByIdMap = {}
          data.forEach(build => {
            buildsByIdMap[build.id] = build
          })
          setBuildsById(prev => ({ ...prev, ...buildsByIdMap }))
        } catch (err) {
          console.error(`Failed to load builds for user ${userId}:`, err)
          setBuildsByUser(prev => ({ ...prev, [userId]: [] })) // Set empty array on error
        }
      })
    )
  }, [user, players, loadedUsers, verifiedClaim])

  // Load build names for assigned builds (for read-only display)
  useEffect(() => {
    if (!players) return
    
    // Get unique build IDs that are assigned but not yet loaded
    const buildIdsToLoad = []
    players.forEach(player => {
      if (player.build_id && !buildsById[player.build_id]) {
        buildIdsToLoad.push(player.build_id)
      }
    })
    
    if (buildIdsToLoad.length === 0) return
    
    // Load build details for assigned builds
    Promise.all(
      buildIdsToLoad.map(async (buildId) => {
        try {
          const build = await getBuild(buildId)
          setBuildsById(prev => ({ ...prev, [buildId]: build }))
        } catch (err) {
          console.error(`Failed to load build ${buildId}:`, err)
        }
      })
    )
  }, [players, buildsById])

  // Handle build assignment
  const handleBuildChange = async (gamePlayerRowId, buildId) => {
    if (!gameId) return
    
    setAssigningBuild(prev => ({ ...prev, [gamePlayerRowId]: true }))
    try {
      await assignBuildToGamePlayer(gameId, gamePlayerRowId, buildId)
      // Reload page to show updated build assignment
      window.location.reload()
    } catch (err) {
      console.error('Failed to assign build:', err)
      alert('Failed to assign build: ' + (err.message || 'Unknown error'))
      setAssigningBuild(prev => ({ ...prev, [gamePlayerRowId]: false }))
    }
  }

  // Sort players by team and row_index
  const sortedPlayers = [...players].sort((a, b) => {
    if (a.side !== b.side) {
      return a.side === 'AWAY' ? -1 : 1
    }
    return a.row_index - b.row_index
  })

  if (!players || players.length === 0) {
    return <p>No player data available</p>
  }

  return (
    <div className="player-table-container rtable-wrap">
      <table className="player-table rtable">
        <thead>
          <tr>
            <th>Team</th>
            <th>Position</th>
            <th>Gamertag</th>
            <th>Grade</th>
            <th>PTS</th>
            <th>REB</th>
            <th>AST</th>
            <th>STL</th>
            <th>BLK</th>
            <th>TOV</th>
            <th>FGM</th>
            <th>FGA</th>
            <th>3PM</th>
            <th>3PA</th>
            <th>FTM</th>
            <th>FTA</th>
            {user && <th>Build</th>}
          </tr>
        </thead>
        <tbody>
          {sortedPlayers.map((player, idx) => (
            <tr key={idx} className={player.side === 'AWAY' ? 'away-player' : 'home-player'}>
              <td data-label="Team">{player.side}</td>
              <td data-label="Position">{player.assigned_position || 'N/A'}</td>
              <td data-label="Gamertag" className="gamertag-cell rtable-primary">{player.gamertag}</td>
              <td data-label="Grade">{player.grade || '-'}</td>
              <td data-label="PTS">{player.stats.pts}</td>
              <td data-label="REB">{player.stats.reb}</td>
              <td data-label="AST">{player.stats.ast}</td>
              <td data-label="STL">{player.stats.stl}</td>
              <td data-label="BLK">{player.stats.blk}</td>
              <td data-label="TOV">{player.stats.tov}</td>
              <td data-label="FGM">{player.stats.fgm}</td>
              <td data-label="FGA">{player.stats.fga}</td>
              <td data-label="3PM">{player.stats.tpm}</td>
              <td data-label="3PA">{player.stats.tpa}</td>
              <td data-label="FTM">{player.stats.ftm}</td>
              <td data-label="FTA">{player.stats.fta}</td>
              <td data-label={user ? 'Build' : ''}>
                {player.game_player_row_id ? (
                  (() => {
                    // Determine if this row is editable
                    const editable = isBuildEditable(player)
                    
                    // Determine which user's builds to show (only if editable)
                    // CRITICAL: Only show builds for the row owner, never the current user unless they own the row
                    let userIdToShow = null
                    const claimOwnerId = player.claim_owner_user_id
                    const userOwnsRow = user ? canAssignBuild(player) : false
                    
                    if (editable && user) {
                      // If row has a claim owner (non-empty string), ALWAYS use that
                      if (claimOwnerId && typeof claimOwnerId === 'string' && claimOwnerId.trim() !== '') {
                        userIdToShow = claimOwnerId
                      } 
                      // Only use current user's builds if:
                      // 1. NOT in edit mode (in edit mode, only show builds for rows with claim owners)
                      // 2. No claim_owner_user_id is set (row is unclaimed)
                      // 3. AND the current user can assign to this row (they own it)
                      // 4. AND the gamertag matches the user's verified claim (not just admin permission)
                      else if (!isEditMode && userOwnsRow && verifiedClaim) {
                        // Double-check: gamertag must match the verified claim's normalized name
                        const normalizedGamertag = (player.gamertag || '').toLowerCase().trim()
                        const normalizedClaim = verifiedClaim.normalized_name?.toLowerCase().trim()
                        if (normalizedGamertag === normalizedClaim) {
                          userIdToShow = user.id
                        }
                        // If gamertag doesn't match, don't show builds (even if user is admin)
                      }
                      // If neither condition is met, userIdToShow stays null (no dropdown)
                    }
                    
                    // CRITICAL SAFETY CHECKS: Never show current user's builds for other users' rows
                    // (Only run these checks if user is logged in)
                    if (user) {
                      // Check 1: If row has a claim owner that's NOT the current user, never show current user's builds
                      if (userIdToShow === user.id && claimOwnerId && claimOwnerId !== user.id) {
                        console.error('ERROR: Attempted to show current user builds for another user\'s row!', {
                          gamertag: player.gamertag,
                          claim_owner_user_id: claimOwnerId,
                          attempted_user_id: userIdToShow,
                          current_user_id: user.id,
                          userOwnsRow
                        })
                        userIdToShow = claimOwnerId
                      }
                      
                      // Check 2: If in edit mode, never show current user's builds unless they own the row
                      if (isEditMode && userIdToShow === user.id && !userOwnsRow) {
                        console.error('ERROR: In edit mode, attempted to show current user builds for row they don\'t own!', {
                          gamertag: player.gamertag,
                          claim_owner_user_id: claimOwnerId,
                          attempted_user_id: userIdToShow,
                          current_user_id: user.id,
                          userOwnsRow
                        })
                        userIdToShow = null
                      }
                      
                      // Check 3: If row has a claim owner, we MUST use that owner's builds (never current user)
                      if (claimOwnerId && claimOwnerId !== user.id && userIdToShow === user.id) {
                        console.error('ERROR: Row has claim owner but showing current user builds!', {
                          gamertag: player.gamertag,
                          claim_owner_user_id: claimOwnerId,
                          attempted_user_id: userIdToShow,
                          current_user_id: user.id
                        })
                        userIdToShow = claimOwnerId
                      }
                      
                      // Check 4: If user doesn't own the row, never show their builds
                      if (userIdToShow === user.id && !userOwnsRow) {
                        console.error('ERROR: Showing current user builds for row they don\'t own!', {
                          gamertag: player.gamertag,
                          claim_owner_user_id: claimOwnerId,
                          attempted_user_id: userIdToShow,
                          current_user_id: user.id,
                          userOwnsRow
                        })
                        userIdToShow = claimOwnerId || null
                      }
                    }
                    
                    const buildsToShow = userIdToShow ? (buildsByUser[userIdToShow] || []) : []
                    
                    if (editable && userIdToShow && buildsToShow.length > 0) {
                      // Editable dropdown (only show if we have builds to show for the correct user)
                      return (
                        <select
                          value={player.build_id || ''}
                          onChange={(e) => {
                            const buildId = e.target.value === '' ? null : parseInt(e.target.value)
                            handleBuildChange(player.game_player_row_id, buildId)
                          }}
                          disabled={assigningBuild[player.game_player_row_id]}
                          style={{
                            padding: '4px 8px',
                            fontSize: '12px',
                            minWidth: '120px'
                          }}
                        >
                          <option value="">None</option>
                          {buildsToShow.map(build => (
                            <option key={build.id} value={build.id}>
                              {formatBuildName(build.display_name)}
                            </option>
                          ))}
                        </select>
                      )
                    } else {
                      // Read-only display (show assigned build name if exists)
                      return (
                        <span style={{ color: 'var(--color-text-secondary)', fontSize: '12px' }}>
                          {player.build_id ? (
                            buildsById[player.build_id]?.display_name 
                              ? formatBuildName(buildsById[player.build_id].display_name)
                              : `Build #${player.build_id}`
                          ) : (
                            <span style={{ color: 'var(--color-text-secondary)' }}>None</span>
                          )}
                        </span>
                      )
                    }
                  })()
                ) : (
                  <span style={{ color: 'var(--color-text-secondary)', fontSize: '12px' }}>N/A</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default PlayerTable

