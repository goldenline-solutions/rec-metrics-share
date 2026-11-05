import { useState, useEffect } from 'react'
import { updateGame, clearGameWarnings, deleteGame, apiUrl, getBuilds, assignBuildToGamePlayer } from '../utils/api'
import './GameEditModal.css'

// Helper function to remove timestamp from build display name
const formatBuildName = (displayName) => {
  if (!displayName) return ''
  // Remove timestamp pattern: " - YYYY-MM-DDTHH:MM:SSZ" or similar ISO date formats
  const timestampPattern = /\s*-\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?/i
  return displayName.replace(timestampPattern, '').trim()
}

/**
 * GameEditModal component - allows admins to edit game data
 * 
 * Props:
 * - game: object - the game data to edit
 * - isOpen: boolean - whether the modal is open
 * - onClose: function - callback to close the modal
 * - onSave: function - callback when game is saved successfully
 * - onDelete: function (optional) - callback when game is deleted (e.g. navigate away)
 */
function GameEditModal({ game, isOpen, onClose, onSave, onDelete }) {
  const [formData, setFormData] = useState(null)
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [clearWarnings, setClearWarnings] = useState(false)
  const [showScreenshot, setShowScreenshot] = useState(true)
  const [activeTab, setActiveTab] = useState('metadata')
  const [buildsByUser, setBuildsByUser] = useState({}) // Map of user_id -> builds array
  const [buildsById, setBuildsById] = useState({}) // Map of build_id -> build object (for display)
  const [loadedUsers, setLoadedUsers] = useState(new Set()) // Track which users we've loaded builds for
  const [assigningBuild, setAssigningBuild] = useState({}) // Track which builds are being assigned

  // Generate default 10 matchups based on player positions
  const generateDefaultMatchups = (players) => {
    const positions = ['PG', 'SG', 'SF', 'PF', 'C']
    const matchups = []
    
    // Create a map of position -> player for each team
    // Only include players with gamertags
    const homePlayersByPos = {}
    const awayPlayersByPos = {}
    
    players.forEach(player => {
      const pos = player.assigned_position || player.position
      const gamertag = (player.gamertag || '').trim()
      if (!gamertag) {
        return // Skip empty slots
      }
      
      if (player.side === 'HOME') {
        homePlayersByPos[pos] = gamertag
      } else if (player.side === 'AWAY') {
        awayPlayersByPos[pos] = gamertag
      }
    })
    
    // Generate 10 matchups: 5 positions × 2 directions
    positions.forEach(position => {
      const homePlayer = homePlayersByPos[position] || ''
      const awayPlayer = awayPlayersByPos[position] || ''
      
      // HOME defender vs AWAY offender
      matchups.push({
        defender_gamertag: homePlayer,
        offender_gamertag: awayPlayer,
        defender_position: position,
        offender_position: position,
        matchup_type: 'POSITIONAL'
      })
      
      // AWAY defender vs HOME offender
      matchups.push({
        defender_gamertag: awayPlayer,
        offender_gamertag: homePlayer,
        defender_position: position,
        offender_position: position,
        matchup_type: 'POSITIONAL'
      })
    })
    
    return matchups
  }

  // Ensure 5 players per team, organized by position
  const ensureFivePlayersPerTeam = (players) => {
    const positions = ['PG', 'SG', 'SF', 'PF', 'C']
    const teams = ['AWAY', 'HOME']
    const organizedPlayers = []
    
    teams.forEach(team => {
      positions.forEach((position, index) => {
        // Find existing player for this team and position
        const existingPlayer = players.find(p => 
          p.side === team && (p.assigned_position === position || p.position === position)
        )
        
        if (existingPlayer) {
          organizedPlayers.push({
            ...existingPlayer,
            assigned_position: position,
            row_index: index
          })
        } else {
          // Create empty placeholder
          organizedPlayers.push({
            side: team,
            row_index: index,
            gamertag: '',
            grade: '',
            assigned_position: position,
            stats: {
              pts: 0,
              reb: 0,
              ast: 0,
              stl: 0,
              blk: 0,
              fouls: 0,
              tov: 0,
              fgm: 0,
              fga: 0,
              tpm: 0,
              tpa: 0,
              ftm: 0,
              fta: 0
            }
          })
        }
      })
    })
    
    return organizedPlayers
  }

  // Initialize form data when game changes
  useEffect(() => {
    if (game && game.payload) {
      const payload = game.payload
      const players = payload.players || []
      
      // Ensure 5 players per team (10 total)
      const organizedPlayers = ensureFivePlayersPerTeam(players)
      
      // Generate 10 matchups (5 positions × 2 directions) if not present
      let matchups = payload.matchups || []
      
      // If we don't have exactly 10 matchups, generate them
      if (matchups.length !== 10) {
        matchups = generateDefaultMatchups(organizedPlayers)
      }
      
      setFormData({
        // Game metadata
        season_label: payload.metadata?.season_label || '',
        mode_label: payload.metadata?.mode_label || '',
        platform: game.platform || '',
        away_team_name: game.payload.game?.away_team_name || '',
        home_team_name: game.payload.game?.home_team_name || '',
        
        // Scores
        away_score: payload.game?.away_score || 0,
        home_score: payload.game?.home_score || 0,
        
        // Quarters
        quarters: {
          away: payload.game?.quarters?.away || [0, 0, 0, 0],
          home: payload.game?.quarters?.home || [0, 0, 0, 0]
        },
        
        // Teams
        teams: payload.teams || [],
        
        // Players - always 10 (5 per team)
        // Preserve game_player_row_id, claim_owner_user_id, and build_id from original players
        players: organizedPlayers.map(orgPlayer => {
          const originalPlayer = players.find(p => 
            p.side === orgPlayer.side && 
            (p.assigned_position === orgPlayer.assigned_position || p.position === orgPlayer.assigned_position) &&
            p.gamertag === orgPlayer.gamertag
          )
          return {
            ...orgPlayer,
            game_player_row_id: originalPlayer?.game_player_row_id,
            claim_owner_user_id: originalPlayer?.claim_owner_user_id,
            build_id: originalPlayer?.build_id
          }
        }),
        
        // Matchups - always exactly 10
        matchups: matchups
      })
      setErrors({})
      setClearWarnings(false)
    }
  }, [game])

  if (!isOpen || !formData) {
    return null
  }

  const handleChange = (path, value) => {
    const keys = path.split('.')
    setFormData(prev => {
      const newData = { ...prev }
      let current = newData
      
      for (let i = 0; i < keys.length - 1; i++) {
        if (Array.isArray(current[keys[i]])) {
          current[keys[i]] = [...current[keys[i]]]
        } else {
          current[keys[i]] = { ...current[keys[i]] }
        }
        current = current[keys[i]]
      }
      
      current[keys[keys.length - 1]] = value
      return newData
    })
    
    // Clear error for this field
    if (errors[path]) {
      setErrors(prev => {
        const newErrors = { ...prev }
        delete newErrors[path]
        return newErrors
      })
    }
  }

  const handleTeamChange = (teamIndex, field, value) => {
    setFormData(prev => {
      const newTeams = [...prev.teams]
      if (field.startsWith('totals.')) {
        const totalField = field.replace('totals.', '')
        newTeams[teamIndex] = {
          ...newTeams[teamIndex],
          totals: {
            ...newTeams[teamIndex].totals,
            [totalField]: parseInt(value) || 0
          }
        }
      } else {
        newTeams[teamIndex] = {
          ...newTeams[teamIndex],
          [field]: value
        }
      }
      return { ...prev, teams: newTeams }
    })
  }

  const handlePlayerChange = (playerIndex, field, value) => {
    setFormData(prev => {
      const newPlayers = [...prev.players]
      if (field.startsWith('stats.')) {
        const statField = field.replace('stats.', '')
        newPlayers[playerIndex] = {
          ...newPlayers[playerIndex],
          stats: {
            ...newPlayers[playerIndex].stats,
            [statField]: parseInt(value) || 0
          }
        }
        return { ...prev, players: newPlayers }
      }

      newPlayers[playerIndex] = { ...newPlayers[playerIndex], [field]: value }

      // When a gamertag changes, sync the old name in any matchup entries
      if (field === 'gamertag') {
        const oldTag = prev.players[playerIndex].gamertag
        const newMatchups = prev.matchups.map(m => ({
          ...m,
          defender_gamertag: m.defender_gamertag === oldTag ? value : m.defender_gamertag,
          offender_gamertag: m.offender_gamertag === oldTag ? value : m.offender_gamertag,
        }))
        return { ...prev, players: newPlayers, matchups: newMatchups }
      }

      return { ...prev, players: newPlayers }
    })
  }

  const handleMatchupChange = (matchupIndex, field, value) => {
    setFormData(prev => {
      const newMatchups = [...prev.matchups]
      newMatchups[matchupIndex] = {
        ...newMatchups[matchupIndex],
        [field]: value
      }
      return { ...prev, matchups: newMatchups }
    })
  }

  const regenerateMatchups = () => {
    setFormData(prev => {
      const newMatchups = generateDefaultMatchups(prev.players)
      return { ...prev, matchups: newMatchups }
    })
  }

  const handleBuildChange = async (gamePlayerRowId, buildId) => {
    if (!game?.game_id) return
    setAssigningBuild(prev => ({ ...prev, [gamePlayerRowId]: true }))
    try {
      await assignBuildToGamePlayer(game.game_id, gamePlayerRowId, buildId ?? null)
      setFormData(prev => ({
        ...prev,
        players: prev.players.map(p =>
          p.game_player_row_id === gamePlayerRowId ? { ...p, build_id: buildId } : p
        )
      }))
    } finally {
      setAssigningBuild(prev => ({ ...prev, [gamePlayerRowId]: false }))
    }
  }

  const validateForm = () => {
    const newErrors = {}
    
    // Validate scores are non-negative integers
    if (formData.away_score < 0 || !Number.isInteger(Number(formData.away_score))) {
      newErrors['away_score'] = 'Away score must be a non-negative integer'
    }
    if (formData.home_score < 0 || !Number.isInteger(Number(formData.home_score))) {
      newErrors['home_score'] = 'Home score must be a non-negative integer'
    }
    
    // Validate quarters are arrays of 4 non-negative integers
    if (formData.quarters.away.length !== 4) {
      newErrors['quarters.away'] = 'Away quarters must have 4 values'
    }
    if (formData.quarters.home.length !== 4) {
      newErrors['quarters.home'] = 'Home quarters must have 4 values'
    }
    
    formData.quarters.away.forEach((q, i) => {
      if (q < 0 || !Number.isInteger(Number(q))) {
        newErrors[`quarters.away.${i}`] = 'Quarter value must be a non-negative integer'
      }
    })
    
    formData.quarters.home.forEach((q, i) => {
      if (q < 0 || !Number.isInteger(Number(q))) {
        newErrors[`quarters.home.${i}`] = 'Quarter value must be a non-negative integer'
      }
    })
    
    // Validate teams
    formData.teams.forEach((team, teamIndex) => {
      if (team.totals) {
        Object.keys(team.totals).forEach(stat => {
          const value = team.totals[stat]
          if (value < 0 || !Number.isInteger(Number(value))) {
            newErrors[`teams.${teamIndex}.totals.${stat}`] = `${stat} must be a non-negative integer`
          }
        })
        
        // Validate shooting stats: made <= attempted
        if (team.totals.fgm > team.totals.fga) {
          newErrors[`teams.${teamIndex}.totals.fgm`] = 'Field goals made cannot exceed attempts'
        }
        if (team.totals.tpm > team.totals.tpa) {
          newErrors[`teams.${teamIndex}.totals.tpm`] = 'Three pointers made cannot exceed attempts'
        }
        if (team.totals.ftm > team.totals.fta) {
          newErrors[`teams.${teamIndex}.totals.ftm`] = 'Free throws made cannot exceed attempts'
        }
      }
    })
    
    // Validate players
    formData.players.forEach((player, playerIndex) => {
      if (player.stats) {
        Object.keys(player.stats).forEach(stat => {
          const value = player.stats[stat]
          if (value < 0 || !Number.isInteger(Number(value))) {
            newErrors[`players.${playerIndex}.stats.${stat}`] = `${stat} must be a non-negative integer`
          }
        })
        
        // Validate shooting stats: made <= attempted
        if (player.stats.fgm > player.stats.fga) {
          newErrors[`players.${playerIndex}.stats.fgm`] = 'Field goals made cannot exceed attempts'
        }
        if (player.stats.tpm > player.stats.tpa) {
          newErrors[`players.${playerIndex}.stats.tpm`] = 'Three pointers made cannot exceed attempts'
        }
        if (player.stats.ftm > player.stats.fta) {
          newErrors[`players.${playerIndex}.stats.ftm`] = 'Free throws made cannot exceed attempts'
        }
      }
    })
    
    // Validate matchups - must have exactly 10
    if (!formData.matchups || formData.matchups.length !== 10) {
      newErrors['matchups'] = 'Must have exactly 10 matchups (5 positions × 2 directions)'
    } else {
      // Validate each matchup has required fields
      formData.matchups.forEach((matchup, matchupIndex) => {
        if (!matchup.defender_gamertag) {
          newErrors[`matchups.${matchupIndex}.defender_gamertag`] = 'Defender gamertag is required'
        }
        if (!matchup.offender_gamertag) {
          newErrors[`matchups.${matchupIndex}.offender_gamertag`] = 'Offender gamertag is required'
        }
        if (!matchup.defender_position) {
          newErrors[`matchups.${matchupIndex}.defender_position`] = 'Defender position is required'
        }
        if (!matchup.offender_position) {
          newErrors[`matchups.${matchupIndex}.offender_position`] = 'Offender position is required'
        }
      })
    }
    
    setErrors(newErrors)
    return { isValid: Object.keys(newErrors).length === 0, errors: newErrors }
  }

  // Helper function to safely convert to number, defaulting to 0
  const safeNumber = (value) => {
    if (value === null || value === undefined || value === '') return 0
    const num = Number(value)
    return isNaN(num) ? 0 : Math.max(0, Math.floor(num))
  }

  // Helper function to safely get string or null
  const safeString = (value) => {
    if (!value || (typeof value === 'string' && value.trim() === '')) return null
    return String(value).trim() || null
  }

  // Check if warnings are resolved by the current form data
  const areWarningsResolved = (warnings, formData) => {
    if (!warnings || warnings.length === 0) return true
    
    // Check for "Player missing stats" warnings
    const missingStatsWarnings = warnings.filter(w => w.includes('missing stats'))
    if (missingStatsWarnings.length > 0) {
      // Check if all players with gamertags have stats
      const playersWithGamertags = formData.players.filter(p => {
        const gamertag = safeString(p.gamertag)
        return gamertag && gamertag !== ''
      })
      
      const playersWithStats = playersWithGamertags.filter(p => {
        const stats = p.stats || {}
        // Check if player has at least some stats (not all zeros or missing)
        return stats.pts !== undefined || stats.reb !== undefined || stats.ast !== undefined
      })
      
      // If not all players with gamertags have stats, warnings not resolved
      if (playersWithGamertags.length > playersWithStats.length) {
        return false
      }
    }
    
    // Check for math mismatches (points, rebounds, assists)
    const mathWarnings = warnings.filter(w => 
      w.includes("don't match team total") || 
      w.includes("exceeds attempts")
    )
    
    if (mathWarnings.length > 0) {
      // Check each team
      for (const team of formData.teams || []) {
        const teamSide = team.side
        if (!teamSide) continue
        
        const teamPlayers = (formData.players || []).filter(p => p.side === teamSide)
        
        // Sum player stats
        const totalPlayerPts = teamPlayers.reduce((sum, p) => sum + safeNumber(p.stats?.pts), 0)
        const totalPlayerReb = teamPlayers.reduce((sum, p) => sum + safeNumber(p.stats?.reb), 0)
        const totalPlayerAst = teamPlayers.reduce((sum, p) => sum + safeNumber(p.stats?.ast), 0)
        const totalPlayerFgm = teamPlayers.reduce((sum, p) => sum + safeNumber(p.stats?.fgm), 0)
        const totalPlayerFga = teamPlayers.reduce((sum, p) => sum + safeNumber(p.stats?.fga), 0)
        const totalPlayerTpm = teamPlayers.reduce((sum, p) => sum + safeNumber(p.stats?.tpm), 0)
        const totalPlayerTpa = teamPlayers.reduce((sum, p) => sum + safeNumber(p.stats?.tpa), 0)
        
        const teamTotal = team.totals || {}
        const teamPts = safeNumber(teamTotal.pts)
        const teamReb = safeNumber(teamTotal.reb)
        const teamAst = safeNumber(teamTotal.ast)
        const teamFgm = safeNumber(teamTotal.fgm)
        const teamFga = safeNumber(teamTotal.fga)
        const teamTpm = safeNumber(teamTotal.tpm)
        const teamTpa = safeNumber(teamTotal.tpa)
        
        // Check for points mismatch
        if (mathWarnings.some(w => w.includes(`${teamSide} team: Player points`))) {
          if (Math.abs(totalPlayerPts - teamPts) > 1) {
            return false
          }
        }
        
        // Check for rebounds mismatch
        if (mathWarnings.some(w => w.includes(`${teamSide} team: Player rebounds`))) {
          if (Math.abs(totalPlayerReb - teamReb) > 2) {
            return false
          }
        }
        
        // Check for assists mismatch
        if (mathWarnings.some(w => w.includes(`${teamSide} team: Player assists`))) {
          if (Math.abs(totalPlayerAst - teamAst) > 1) {
            return false
          }
        }
        
        // Check for shooting stats issues - player totals
        if (mathWarnings.some(w => w.includes(`${teamSide} team: Field goals made`) && w.includes('exceeds attempts') && !w.includes('Team'))) {
          if (totalPlayerFgm > totalPlayerFga) {
            return false
          }
        }
        
        if (mathWarnings.some(w => w.includes(`${teamSide} team: 3-pointers made`) && w.includes('exceeds attempts') && !w.includes('Team'))) {
          if (totalPlayerTpm > totalPlayerTpa) {
            return false
          }
        }
        
        // Check for shooting stats issues - team totals
        if (mathWarnings.some(w => w.includes(`${teamSide} team: Team field goals made`) && w.includes('exceeds attempts'))) {
          if (teamFgm > teamFga) {
            return false
          }
        }
        
        if (mathWarnings.some(w => w.includes(`${teamSide} team: Team 3-pointers made`) && w.includes('exceeds attempts'))) {
          if (teamTpm > teamTpa) {
            return false
          }
        }
      }
    }
    
    return true
  }

  const handleSave = async () => {
    setSaving(true)
    
    try {
      // Prepare update data with defaults
      const updateData = {
        away_score: safeNumber(formData.away_score),
        home_score: safeNumber(formData.home_score),
        season_label: safeString(formData.season_label),
        mode_label: safeString(formData.mode_label),
        platform: safeString(formData.platform),
        away_team_name: safeString(formData.away_team_name),
        home_team_name: safeString(formData.home_team_name),
        quarters: {
          away: (formData.quarters?.away || []).map(q => safeNumber(q)).slice(0, 4).concat(Array(4).fill(0)).slice(0, 4),
          home: (formData.quarters?.home || []).map(q => safeNumber(q)).slice(0, 4).concat(Array(4).fill(0)).slice(0, 4)
        },
        teams: (formData.teams || []).map(team => ({
          ...team,
          grade: safeString(team.grade),
          totals: {
            pts: safeNumber(team.totals?.pts),
            reb: safeNumber(team.totals?.reb),
            ast: safeNumber(team.totals?.ast),
            stl: safeNumber(team.totals?.stl),
            blk: safeNumber(team.totals?.blk),
            fouls: safeNumber(team.totals?.fouls),
            tov: safeNumber(team.totals?.tov),
            fgm: safeNumber(team.totals?.fgm),
            fga: safeNumber(team.totals?.fga),
            tpm: safeNumber(team.totals?.tpm),
            tpa: safeNumber(team.totals?.tpa),
            ftm: safeNumber(team.totals?.ftm),
            fta: safeNumber(team.totals?.fta)
          }
        })),
        players: (formData.players || []).map(player => ({
          ...player,
          gamertag: safeString(player.gamertag) || '',
          grade: safeString(player.grade),
          stats: {
            pts: safeNumber(player.stats?.pts),
            reb: safeNumber(player.stats?.reb),
            ast: safeNumber(player.stats?.ast),
            stl: safeNumber(player.stats?.stl),
            blk: safeNumber(player.stats?.blk),
            fouls: safeNumber(player.stats?.fouls),
            tov: safeNumber(player.stats?.tov),
            fgm: safeNumber(player.stats?.fgm),
            fga: safeNumber(player.stats?.fga),
            tpm: safeNumber(player.stats?.tpm),
            tpa: safeNumber(player.stats?.tpa),
            ftm: safeNumber(player.stats?.ftm),
            fta: safeNumber(player.stats?.fta)
          }
        })),
        matchups: (formData.matchups || []).map(matchup => ({
          defender_gamertag: safeString(matchup.defender_gamertag) || '',
          offender_gamertag: safeString(matchup.offender_gamertag) || '',
          defender_position: safeString(matchup.defender_position) || 'PG',
          offender_position: safeString(matchup.offender_position) || 'PG',
          matchup_type: safeString(matchup.matchup_type) || 'POSITIONAL'
        }))
      }
      
      // Update game
      await updateGame(game.game_id, updateData)
      
      // Clear warnings only if checkbox is checked OR warnings are actually resolved
      const warningsResolved = areWarningsResolved(game.warnings || [], formData)
      if (clearWarnings || warningsResolved) {
        await clearGameWarnings(game.game_id)
      }
      
      // Call onSave callback to refresh data
      if (onSave) {
        onSave()
      }
      
      onClose()
    } catch (error) {
      setErrors({ _general: error.message || 'Failed to save game data' })
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    const confirmed = window.confirm(
      'Are you sure you want to delete this game? This cannot be undone.'
    )
    if (!confirmed) return
    setDeleting(true)
    try {
      await deleteGame(game.game_id)
      if (onSave) onSave()
      if (onDelete) onDelete()
      onClose()
    } catch (error) {
      setErrors({ _general: error.message || 'Failed to delete game' })
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content game-edit-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ flex: 1 }}>
            <h2>Edit Game Data</h2>
            {game.needs_verification && game.warnings && game.warnings.length > 0 && (
              <div className="warning-banner-header" style={{
                backgroundColor: 'var(--color-warning-muted)',
                border: '2px solid var(--color-warning)',
                borderRadius: '6px',
                padding: '10px 12px',
                marginTop: '10px',
                fontSize: '13px'
              }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                  <span style={{ fontSize: '18px', flexShrink: 0 }}>⚠️</span>
                  <div style={{ flex: 1 }}>
                    <strong style={{ color: 'var(--color-warning)', display: 'block', marginBottom: '4px' }}>
                      Data Needs Verification
                    </strong>
                    <ul style={{ margin: 0, paddingLeft: '18px', color: 'var(--color-warning)', fontSize: '12px' }}>
                      {game.warnings.map((warning, idx) => (
                        <li key={idx} style={{ marginBottom: '2px' }}>{warning}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            )}
          </div>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        
        {/* Screenshot at top */}
        {game.screenshot_url && (
          <div className="screenshot-top-section">
            <div className="screenshot-top-header">
              <h3>Original Screenshot</h3>
              <button 
                type="button"
                onClick={() => setShowScreenshot(!showScreenshot)}
                style={{
                  padding: '6px 12px',
                  backgroundColor: 'var(--color-text-secondary)',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '12px'
                }}
              >
                {showScreenshot ? 'Hide' : 'Show'}
              </button>
            </div>
            {showScreenshot && (
              <div className="screenshot-top-container">
                <img 
                  src={apiUrl(game.screenshot_url)} 
                  alt="Game screenshot" 
                  className="screenshot-top-image"
                />
              </div>
            )}
          </div>
        )}

        {/* Tabs */}
        <div className="modal-tabs">
          <button
            className={`tab-button ${activeTab === 'metadata' ? 'active' : ''}`}
            onClick={() => setActiveTab('metadata')}
          >
            Metadata
          </button>
          <button
            className={`tab-button ${activeTab === 'home-players' ? 'active' : ''}`}
            onClick={() => setActiveTab('home-players')}
          >
            Home Team Players
          </button>
          <button
            className={`tab-button ${activeTab === 'away-players' ? 'active' : ''}`}
            onClick={() => setActiveTab('away-players')}
          >
            Away Team Players
          </button>
          <button
            className={`tab-button ${activeTab === 'quarters' ? 'active' : ''}`}
            onClick={() => setActiveTab('quarters')}
          >
            Quarter Scores
          </button>
          <button
            className={`tab-button ${activeTab === 'team-totals' ? 'active' : ''}`}
            onClick={() => setActiveTab('team-totals')}
          >
            Team Totals
          </button>
          <button
            className={`tab-button ${activeTab === 'matchups' ? 'active' : ''}`}
            onClick={() => setActiveTab('matchups')}
          >
            Matchups
          </button>
        </div>

        <div className="modal-body">
          <div className="form-panel">
            {errors._general && (
              <div className="error-message">{errors._general}</div>
            )}
            
            {activeTab === 'metadata' && (
              <div className="form-section-compact">
                <h3>Game &amp; scores</h3>
                <div className="form-row-compact">
                  <label>
                    Season
                    <input
                      type="text"
                      value={formData.season_label}
                      onChange={(e) => handleChange('season_label', e.target.value)}
                      placeholder="Season"
                    />
                  </label>
                  <label>
                    Mode
                    <input
                      type="text"
                      value={formData.mode_label}
                      onChange={(e) => handleChange('mode_label', e.target.value)}
                      placeholder="Mode"
                    />
                  </label>
                  <label>
                    Platform
                    <select
                      value={formData.platform || ''}
                      onChange={(e) => handleChange('platform', e.target.value)}
                    >
                      <option value="">Select platform</option>
                      <option value="PC">PC</option>
                      <option value="Console">Console</option>
                    </select>
                  </label>
                  <label>
                    Away team
                    <input
                      type="text"
                      value={formData.away_team_name}
                      onChange={(e) => handleChange('away_team_name', e.target.value)}
                      placeholder="Away"
                    />
                  </label>
                  <label>
                    Home team
                    <input
                      type="text"
                      value={formData.home_team_name}
                      onChange={(e) => handleChange('home_team_name', e.target.value)}
                      placeholder="Home"
                    />
                  </label>
                  <label>
                    Away score
                    <input
                      type="number"
                      min="0"
                      value={formData.away_score}
                      onChange={(e) => handleChange('away_score', parseInt(e.target.value) || 0)}
                      className={errors.away_score ? 'error' : ''}
                    />
                    {errors.away_score && <span className="field-error">{errors.away_score}</span>}
                  </label>
                  <label>
                    Home score
                    <input
                      type="number"
                      min="0"
                      value={formData.home_score}
                      onChange={(e) => handleChange('home_score', parseInt(e.target.value) || 0)}
                      className={errors.home_score ? 'error' : ''}
                    />
                    {errors.home_score && <span className="field-error">{errors.home_score}</span>}
                  </label>
                </div>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={clearWarnings}
                    onChange={(e) => setClearWarnings(e.target.checked)}
                  />
                  Clear warnings from this game
                </label>
              </div>
            )}

            {activeTab === 'home-players' && (
              <div className="form-section-compact">
                <h3>{formData.home_team_name || 'Home'} — players</h3>
                <div className="edit-table-wrap">
                  <table className="edit-table">
                    <thead>
                      <tr>
                        <th>Pos</th>
                        <th>Gamertag</th>
                        <th>Grade</th>
                        <th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th>
                        <th>Fouls</th><th>TOV</th>
                        <th>FGM</th><th>FGA</th><th>3PM</th><th>3PA</th><th>FTM</th><th>FTA</th>
                        <th>Build</th>
                      </tr>
                    </thead>
                    <tbody>
                      {formData.players.filter(p => p.side === 'HOME').map((player) => {
                        const playerIndex = formData.players.findIndex(px => px.side === 'HOME' && px.assigned_position === player.assigned_position)
                        const buildsToShow = player.claim_owner_user_id ? (buildsByUser[player.claim_owner_user_id] || []) : []
                        return (
                          <tr key={playerIndex}>
                            <td className="col-num">{player.assigned_position}</td>
                            <td>
                              <input
                                type="text"
                                className="edit-table-input-wide"
                                value={player.gamertag || ''}
                                onChange={(e) => handlePlayerChange(playerIndex, 'gamertag', e.target.value)}
                                placeholder="Gamertag"
                              />
                            </td>
                            <td>
                              <input type="text" value={player.grade || ''} onChange={(e) => handlePlayerChange(playerIndex, 'grade', e.target.value)} placeholder="—" style={{ maxWidth: '48px' }} />
                            </td>
                            {['pts', 'reb', 'ast', 'stl', 'blk', 'fouls', 'tov', 'fgm', 'fga', 'tpm', 'tpa', 'ftm', 'fta'].map(stat => (
                              <td key={stat}>
                                <input
                                  type="number"
                                  min="0"
                                  value={player.stats?.[stat] ?? 0}
                                  onChange={(e) => handlePlayerChange(playerIndex, `stats.${stat}`, e.target.value)}
                                  className={errors[`players.${playerIndex}.stats.${stat}`] ? 'error' : ''}
                                />
                              </td>
                            ))}
                            <td>
                              {player.game_player_row_id && buildsToShow.length > 0 ? (
                                <select
                                  value={player.build_id || ''}
                                  onChange={(e) => handleBuildChange(player.game_player_row_id, e.target.value === '' ? null : parseInt(e.target.value))}
                                  disabled={assigningBuild[player.game_player_row_id]}
                                >
                                  <option value="">None</option>
                                  {buildsToShow.map(build => (
                                    <option key={build.id} value={build.id}>{formatBuildName(build.display_name)}</option>
                                  ))}
                                </select>
                              ) : player.game_player_row_id ? (
                                <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>{player.claim_owner_user_id ? 'No builds' : '—'}</span>
                              ) : null}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {activeTab === 'away-players' && (
              <div className="form-section-compact">
                <h3>{formData.away_team_name || 'Away'} — players</h3>
                <div className="edit-table-wrap">
                  <table className="edit-table">
                    <thead>
                      <tr>
                        <th>Pos</th>
                        <th>Gamertag</th>
                        <th>Grade</th>
                        <th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th>
                        <th>Fouls</th><th>TOV</th>
                        <th>FGM</th><th>FGA</th><th>3PM</th><th>3PA</th><th>FTM</th><th>FTA</th>
                        <th>Build</th>
                      </tr>
                    </thead>
                    <tbody>
                      {formData.players.filter(p => p.side === 'AWAY').map((player) => {
                        const playerIndex = formData.players.findIndex(px => px.side === 'AWAY' && px.assigned_position === player.assigned_position)
                        const buildsToShow = player.claim_owner_user_id ? (buildsByUser[player.claim_owner_user_id] || []) : []
                        return (
                          <tr key={playerIndex}>
                            <td className="col-num">{player.assigned_position}</td>
                            <td>
                              <input
                                type="text"
                                className="edit-table-input-wide"
                                value={player.gamertag || ''}
                                onChange={(e) => handlePlayerChange(playerIndex, 'gamertag', e.target.value)}
                                placeholder="Gamertag"
                              />
                            </td>
                            <td>
                              <input type="text" value={player.grade || ''} onChange={(e) => handlePlayerChange(playerIndex, 'grade', e.target.value)} placeholder="—" style={{ maxWidth: '48px' }} />
                            </td>
                            {['pts', 'reb', 'ast', 'stl', 'blk', 'fouls', 'tov', 'fgm', 'fga', 'tpm', 'tpa', 'ftm', 'fta'].map(stat => (
                              <td key={stat}>
                                <input
                                  type="number"
                                  min="0"
                                  value={player.stats?.[stat] ?? 0}
                                  onChange={(e) => handlePlayerChange(playerIndex, `stats.${stat}`, e.target.value)}
                                  className={errors[`players.${playerIndex}.stats.${stat}`] ? 'error' : ''}
                                />
                              </td>
                            ))}
                            <td>
                              {player.game_player_row_id && buildsToShow.length > 0 ? (
                                <select
                                  value={player.build_id || ''}
                                  onChange={(e) => handleBuildChange(player.game_player_row_id, e.target.value === '' ? null : parseInt(e.target.value))}
                                  disabled={assigningBuild[player.game_player_row_id]}
                                >
                                  <option value="">None</option>
                                  {buildsToShow.map(build => (
                                    <option key={build.id} value={build.id}>{formatBuildName(build.display_name)}</option>
                                  ))}
                                </select>
                              ) : player.game_player_row_id ? (
                                <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>{player.claim_owner_user_id ? 'No builds' : '—'}</span>
                              ) : null}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {activeTab === 'quarters' && (
              <div className="form-section-compact">
                <h3>Quarter scores</h3>
                <div className="edit-table-wrap">
                  <table className="edit-table">
                    <thead>
                      <tr>
                        <th></th>
                        <th>Away</th>
                        <th>Home</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[0, 1, 2, 3].map(i => (
                        <tr key={i}>
                          <td className="col-num"><strong>Q{i + 1}</strong></td>
                          <td>
                            <input
                              type="number"
                              min="0"
                              value={formData.quarters.away[i] ?? 0}
                              onChange={(e) => {
                                const newQuarters = [...formData.quarters.away]
                                newQuarters[i] = parseInt(e.target.value) || 0
                                handleChange('quarters.away', newQuarters)
                              }}
                              className={errors[`quarters.away.${i}`] ? 'error' : ''}
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              min="0"
                              value={formData.quarters.home[i] ?? 0}
                              onChange={(e) => {
                                const newQuarters = [...formData.quarters.home]
                                newQuarters[i] = parseInt(e.target.value) || 0
                                handleChange('quarters.home', newQuarters)
                              }}
                              className={errors[`quarters.home.${i}`] ? 'error' : ''}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {activeTab === 'team-totals' && (
              <div className="form-section-compact">
                <h3>Team totals</h3>
                <div className="edit-table-wrap">
                  <table className="edit-table">
                    <thead>
                      <tr>
                        <th>Team</th>
                        <th>Grade</th>
                        <th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th>
                        <th>Fouls</th><th>TOV</th>
                        <th>FGM</th><th>FGA</th><th>3PM</th><th>3PA</th><th>FTM</th><th>FTA</th>
                      </tr>
                    </thead>
                    <tbody>
                      {formData.teams.map((team, teamIndex) => (
                        <tr key={teamIndex}>
                          <td><strong>{team.side}</strong></td>
                          <td>
                            <input
                              type="text"
                              value={team.grade || ''}
                              onChange={(e) => handleTeamChange(teamIndex, 'grade', e.target.value)}
                              style={{ maxWidth: '48px' }}
                            />
                          </td>
                          {['pts', 'reb', 'ast', 'stl', 'blk', 'fouls', 'tov', 'fgm', 'fga', 'tpm', 'tpa', 'ftm', 'fta'].map(stat => (
                            <td key={stat}>
                              <input
                                type="number"
                                min="0"
                                value={team.totals?.[stat] ?? 0}
                                onChange={(e) => handleTeamChange(teamIndex, `totals.${stat}`, e.target.value)}
                                className={errors[`teams.${teamIndex}.totals.${stat}`] ? 'error' : ''}
                              />
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {activeTab === 'matchups' && (
              <div className="form-section-compact">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <h3>Matchups (10 required)</h3>
                  <button type="button" onClick={regenerateMatchups} style={{ padding: '6px 12px', backgroundColor: 'var(--color-accent)', color: 'var(--color-on-accent)', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '13px' }}>
                    Regenerate from positions
                  </button>
                </div>
                {errors.matchups && <div className="error-message" style={{ marginBottom: '10px' }}>{errors.matchups}</div>}
                {formData.matchups && formData.matchups.length === 10 ? (
                  <div className="edit-table-wrap">
                    <table className="edit-table">
                      <thead>
                        <tr>
                          <th className="col-num">#</th>
                          <th>Defender</th>
                          <th>Def Pos</th>
                          <th>Offender</th>
                          <th>Off Pos</th>
                          <th>Type</th>
                        </tr>
                      </thead>
                      <tbody>
                        {formData.matchups.map((matchup, matchupIndex) => {
                          const availablePlayers = [...new Set(formData.players.map(p => p.gamertag).filter(Boolean))]
                          const positions = ['PG', 'SG', 'SF', 'PF', 'C']
                          return (
                            <tr key={matchupIndex}>
                              <td className="col-num">{matchupIndex + 1}</td>
                              <td>
                                <select
                                  value={matchup.defender_gamertag || ''}
                                  onChange={(e) => handleMatchupChange(matchupIndex, 'defender_gamertag', e.target.value)}
                                >
                                  <option value="">—</option>
                                  {availablePlayers.map(g => <option key={g} value={g}>{g}</option>)}
                                </select>
                              </td>
                              <td>
                                <select value={matchup.defender_position || 'PG'} onChange={(e) => handleMatchupChange(matchupIndex, 'defender_position', e.target.value)}>
                                  {positions.map(pos => <option key={pos} value={pos}>{pos}</option>)}
                                </select>
                              </td>
                              <td>
                                <select
                                  value={matchup.offender_gamertag || ''}
                                  onChange={(e) => handleMatchupChange(matchupIndex, 'offender_gamertag', e.target.value)}
                                >
                                  <option value="">—</option>
                                  {availablePlayers.map(g => <option key={g} value={g}>{g}</option>)}
                                </select>
                              </td>
                              <td>
                                <select value={matchup.offender_position || 'PG'} onChange={(e) => handleMatchupChange(matchupIndex, 'offender_position', e.target.value)}>
                                  {positions.map(pos => <option key={pos} value={pos}>{pos}</option>)}
                                </select>
                              </td>
                              <td>
                                <select value={matchup.matchup_type || 'POSITIONAL'} onChange={(e) => handleMatchupChange(matchupIndex, 'matchup_type', e.target.value)}>
                                  <option value="POSITIONAL">Positional</option>
                                  <option value="INDICATED">Indicated</option>
                                </select>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p style={{ color: 'var(--color-negative)', fontSize: '13px' }}>Expected 10 matchups, found {formData.matchups?.length || 0}. Use “Regenerate from positions”.</p>
                )}
              </div>
            )}
          </div>
        </div>
        
        <div className="modal-footer">
          <button
            type="button"
            onClick={handleDelete}
            disabled={saving || deleting}
            className="danger"
            title="Permanently delete this game"
          >
            {deleting ? 'Deleting...' : 'Delete Game'}
          </button>
          <div className="modal-footer-spacer" />
          <button type="button" onClick={onClose} disabled={saving || deleting}>Cancel</button>
          <button type="button" onClick={handleSave} disabled={saving || deleting} className="primary">
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default GameEditModal

