"""
Authentication utilities for Discord OAuth2 and session management.
"""
import os
import hmac
import hashlib
import secrets
import jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Configuration from environment
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
DEV_DISCORD_REDIRECT_URI = os.getenv("DEV_DISCORD_REDIRECT_URI")
DISCORD_OAUTH_STATE_SECRET = os.getenv("DISCORD_OAUTH_STATE_SECRET")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", os.getenv("DISCORD_OAUTH_STATE_SECRET", "change-me-in-production"))

# Discord OAuth2 endpoints
DISCORD_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"

# OAuth2 scopes
DISCORD_SCOPES = ["identify", "email"]


def generate_state():
    """
    Generate a random state string for OAuth2 CSRF protection.
    Returns: (state, signed_state) tuple
    """
    state = secrets.token_urlsafe(32)
    signed_state = sign_state(state)
    return state, signed_state


def sign_state(state):
    """
    Sign a state string using HMAC SHA256.
    Returns: base64-encoded signed state
    """
    if not DISCORD_OAUTH_STATE_SECRET:
        raise ValueError("DISCORD_OAUTH_STATE_SECRET must be set")
    
    signature = hmac.new(
        DISCORD_OAUTH_STATE_SECRET.encode('utf-8'),
        state.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Return state:signature format
    return f"{state}:{signature}"


def verify_state(state_with_signature):
    """
    Verify a signed state string.
    Returns: (is_valid, state) tuple
    """
    if not DISCORD_OAUTH_STATE_SECRET:
        return False, None
    
    try:
        state, signature = state_with_signature.split(':', 1)
    except ValueError:
        return False, None
    
    expected_signature = hmac.new(
        DISCORD_OAUTH_STATE_SECRET.encode('utf-8'),
        state.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Use constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(signature, expected_signature):
        return False, None
    
    return True, state


def get_discord_authorize_url():
    """
    Generate Discord OAuth2 authorization URL with state parameter.
    Returns: (authorize_url, state) tuple
    """
    if not DISCORD_CLIENT_ID or not DISCORD_REDIRECT_URI:
        raise ValueError("DISCORD_CLIENT_ID and DISCORD_REDIRECT_URI must be set")
    
    state, signed_state = generate_state()
    
    if os.getenv("FLASK_ENV") == "development":
        redirect_uri = DEV_DISCORD_REDIRECT_URI
    else:
        redirect_uri = DISCORD_REDIRECT_URI

    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(DISCORD_SCOPES),
        "state": signed_state
    }
    
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    authorize_url = f"{DISCORD_AUTHORIZE_URL}?{query_string}"
    
    return authorize_url, state


def exchange_code_for_token(code):
    """
    Exchange Discord OAuth2 authorization code for access token.
    Returns: access_token (string)
    """
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET or not DISCORD_REDIRECT_URI:
        raise ValueError("Discord OAuth2 credentials must be set")
    
    import requests
    
    if os.getenv("FLASK_ENV") == "development":
        redirect_uri = DEV_DISCORD_REDIRECT_URI
    else:
        redirect_uri = DISCORD_REDIRECT_URI

    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri
    }
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    response = requests.post(DISCORD_TOKEN_URL, data=data, headers=headers)
    response.raise_for_status()
    
    token_data = response.json()
    return token_data.get("access_token")


def get_discord_user_info(access_token):
    """
    Fetch user information from Discord API using access token.
    Returns: dict with user info (id, username, discriminator, avatar, email)
    """
    import requests
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    response = requests.get(DISCORD_USER_URL, headers=headers)
    response.raise_for_status()
    
    return response.json()


def create_session_token(user_id):
    """
    Create a JWT session token for the user.
    Returns: JWT token string
    """
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(days=7),  # Token expires in 7 days
        "iat": datetime.utcnow()
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")
    return token


def verify_session_token(token):
    """
    Verify and decode a JWT session token.
    Returns: (is_valid, user_id) tuple
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
        return True, payload.get("user_id")
    except jwt.ExpiredSignatureError:
        return False, None
    except jwt.InvalidTokenError:
        return False, None

