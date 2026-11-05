import { useAuth } from '../contexts/AuthContext'
import LoginButton from '../components/LoginButton'
import './LoginPage.css'

export default function LoginPage() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="login-page">
        <div className="login-container">
          <div>Loading...</div>
        </div>
      </div>
    )
  }

  if (user) {
    // User is already logged in, redirect or show message
    return (
      <div className="login-page">
        <div className="login-container">
          <h1>Welcome back!</h1>
          <p>You are logged in as {user.display_name || user.username}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="login-page">
      <div className="login-container">
        <h1>Welcome to 2K Stats Desk</h1>
        <p>Please sign in with Discord to continue</p>
        <LoginButton />
      </div>
    </div>
  )
}

