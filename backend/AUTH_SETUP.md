# Discord OAuth2 Authentication Setup Guide

This document explains how to set up Discord OAuth2 authentication for the 2K Stats Desk application.

## Environment Variables

Create a `.env` file in the `backend/` directory with the following variables:

### Required Discord OAuth2 Variables

```bash
# Discord OAuth2 Configuration
# Get these from https://discord.com/developers/applications
DISCORD_CLIENT_ID=your_discord_client_id
DISCORD_CLIENT_SECRET=your_discord_client_secret
DISCORD_REDIRECT_URI=http://localhost:5000/auth/discord/callback
# For production: DISCORD_REDIRECT_URI=https://yourdomain.com/auth/discord/callback

# OAuth State Secret (use a random string for security)
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
DISCORD_OAUTH_STATE_SECRET=your_random_secret_string_here

# JWT Secret Key (for session tokens)
# Can be same as DISCORD_OAUTH_STATE_SECRET or different
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_SECRET_KEY=your_jwt_secret_key_here

# Frontend URL (for OAuth redirect after login)
FRONTEND_URL=http://localhost:5173
# For production: FRONTEND_URL=https://yourdomain.com
```

### Other Required Variables

```bash
# OpenAI Configuration (existing)
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o

# Database Configuration (existing)
DATABASE_URL=sqlite:///app.db
# For PostgreSQL: DATABASE_URL=postgresql://username:password@localhost:5432/nba2k_db

# Server Configuration (existing)
PORT=5000
HOST=127.0.0.1
ENV=development
```

## Setting Up Discord OAuth2

1. **Create a Discord Application:**
   - Go to https://discord.com/developers/applications
   - Click "New Application"
   - Give it a name (e.g., "2K Stats Desk")
   - Click "Create"

2. **Get OAuth2 Credentials:**
   - In your application, go to the "OAuth2" section
   - Copy the "Client ID" → use as `DISCORD_CLIENT_ID`
   - Click "Reset Secret" and copy the secret → use as `DISCORD_CLIENT_SECRET`

3. **Configure Redirect URI:**
   - In the OAuth2 section, under "Redirects", add:
     - For development: `http://localhost:5000/auth/discord/callback`
     - For production: `https://yourdomain.com/auth/discord/callback`
   - Save changes

4. **Set Required Scopes:**
   - The application uses `identify` and `email` scopes
   - These are automatically included in the OAuth flow

## Database Setup

The `users` table will be created automatically when you run the app. SQLAlchemy's `init_db()` function (called in `app.py`) will create any missing tables, including the new `users` table.

**No manual migration needed** - just start the app and the table will be created automatically.

## Installing Dependencies

Make sure to install the new dependency:

```bash
cd backend
pip install -r requirements.txt
```

This will install `PyJWT==2.8.0` which is required for session token management.

## Testing the Setup

See the test checklist in the main README or run through the manual test steps:

1. Start the backend server: `python app.py`
2. Start the frontend dev server: `npm run dev` (in frontend/)
3. Navigate to the login page
4. Click "Continue with Discord"
5. Authorize the application in Discord
6. You should be redirected back and logged in
7. Check that `/api/me` returns your user profile

## Troubleshooting

### "Discord OAuth not configured properly"
- Check that all Discord environment variables are set
- Verify `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, and `DISCORD_REDIRECT_URI` are correct

### "Invalid state parameter"
- This usually means the `DISCORD_OAUTH_STATE_SECRET` is incorrect or changed
- Make sure the secret is the same between server restarts

### "Not authenticated" when calling `/api/me`
- Check that cookies are being sent (browser DevTools → Application → Cookies)
- Verify the cookie name is `access_token` and it's HttpOnly
- Check CORS configuration allows credentials

### CORS Issues
- Make sure `supports_credentials: True` is set in CORS config
- Verify frontend fetch calls include `credentials: 'include'`
- Check that the frontend origin is in the allowed origins list

