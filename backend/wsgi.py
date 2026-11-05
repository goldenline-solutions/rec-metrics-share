"""
WSGI entry point for production deployment.
Use this with waitress or other WSGI servers.
"""
import os
from app import app, init_db
import logging

# Initialize database
try:
    init_db()
except Exception as e:
    logging.error(f"Database initialization error: {e}", exc_info=True)

# This is the WSGI application object
application = app

if __name__ == "__main__":
    # Can also run directly for testing
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "127.0.0.1")
    
    from waitress import serve
    print(f"Starting Waitress server on {host}:{port}")
    serve(application, host=host, port=port)

