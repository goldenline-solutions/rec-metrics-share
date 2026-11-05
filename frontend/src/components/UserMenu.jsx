import { useAuth } from '../contexts/AuthContext'
import LoginButton from './LoginButton'
import './UserMenu.css'

export default function UserMenu() {
  const { user, loading, logout } = useAuth()

  if (loading) {
    return <div className="user-menu">Loading...</div>
  }

  if (!user) {
    return (
      <div className="user-menu">
        <LoginButton />
      </div>
    )
  }

  const displayName = user.display_name || user.username

  return (
    <div className="user-menu">
      <div className="user-info">
        {user.discord_avatar && user.discord_id && (
          <img 
            src={`https://cdn.discordapp.com/avatars/${user.discord_id}/${user.discord_avatar}.png`}
            alt={displayName}
            className="user-avatar"
            onError={(e) => {
              e.target.style.display = 'none'
            }}
          />
        )}
        <span className="user-name">{displayName}</span>
      </div>
      <button onClick={logout} className="logout-button">
        Logout
      </button>
    </div>
  )
}

