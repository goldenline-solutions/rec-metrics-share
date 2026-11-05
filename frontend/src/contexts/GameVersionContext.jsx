import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

/**
 * Which NBA 2K title the site is showing.
 *
 * Games are tagged 2K26 or 2K27 in the database. The choice is site-wide and
 * sticky: pick 2K27 on the leaderboard and the games list, profiles and stats
 * follow, this visit and the next.
 */

export const GAME_VERSIONS = ['2K26', '2K27']

/**
 * Version selected when a visitor has never chosen one.
 *
 * 2K27 is the current title, so that is where visitors land. Until 2K27 games
 * are actually uploaded these views come up empty — the switch on every page
 * is the way back to the 2K26 history.
 */
export const DEFAULT_GAME_VERSION = '2K27'

const STORAGE_KEY = 'recmetrics.gameVersion'

export function normalizeGameVersion(value, fallback = DEFAULT_GAME_VERSION) {
  const normalized = String(value || '').trim().toUpperCase()
  return GAME_VERSIONS.includes(normalized) ? normalized : fallback
}

function readStoredVersion() {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    return stored ? normalizeGameVersion(stored) : DEFAULT_GAME_VERSION
  } catch {
    // Private mode / storage blocked — fall back to the default for this visit.
    return DEFAULT_GAME_VERSION
  }
}

const GameVersionContext = createContext({
  gameVersion: DEFAULT_GAME_VERSION,
  setGameVersion: () => {},
})

export function GameVersionProvider({ children }) {
  const [gameVersion, setGameVersionState] = useState(readStoredVersion)

  const setGameVersion = useCallback((next) => {
    setGameVersionState(normalizeGameVersion(next))
  }, [])

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, gameVersion)
    } catch {
      // Storage unavailable: the choice still holds for this session.
    }
  }, [gameVersion])

  const value = useMemo(
    () => ({ gameVersion, setGameVersion }),
    [gameVersion, setGameVersion]
  )

  return (
    <GameVersionContext.Provider value={value}>
      {children}
    </GameVersionContext.Provider>
  )
}

export function useGameVersion() {
  return useContext(GameVersionContext)
}
