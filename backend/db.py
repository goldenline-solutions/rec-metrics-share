"""
Database configuration and session management.
Supports SQLite (default) and PostgreSQL via DATABASE_URL.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()
# Switch to local SQL Server
# DATABASE_URL = "mssql+pyodbc://localhost:1433/nba2k_db?driver=ODBC+Driver+17+for+SQL+Server"
# Default to SQLite if DATABASE_URL not set
# DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")
DATABASE_URL = os.environ["PG_DATABASE_URL"]  # e.g. postgresql+psycopg2://USER:PASSWORD@localhost:5432/app_db

# Create engine with appropriate settings
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
        future=True,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=True,  # helps on Windows/services
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """
    Initialize the database by creating all tables.
    Call this once when setting up the application.
    """
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Only run your custom file-based migrations for SQLite
    if str(engine.url).startswith("sqlite"):
        run_migrations()

# Create engine with appropriate settings
# if DATABASE_URL.startswith("sqlite"):
#     # SQLite-specific settings
#     engine = create_engine(
#         DATABASE_URL,
#         connect_args={"check_same_thread": False},  # Needed for SQLite with Flask
#         echo=False  # Set to True for SQL query logging
#     )
# else:
#     # PostgreSQL or other database
#     engine = create_engine(
#         DATABASE_URL,
#         echo=False
#     )

# # Session factory
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# # Base class for models
# Base = declarative_base()


# def get_db():
#     """
#     Dependency function to get a database session.
#     Yields a session and ensures it's closed after use.
#     """
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()


# def init_db():
#     """
#     Initialize the database by creating all tables.
#     Call this once when setting up the application.
#     Also runs pending migrations.
#     """
#     # Import models to register them with Base
#     import models  # noqa: F401
#     Base.metadata.create_all(bind=engine)
    
#     # Run pending migrations
#     run_migrations()


def run_migrations():
    """
    Run all pending SQL migrations.
    """
    import os
    from pathlib import Path
    
    # Get database path from engine
    db_url = str(engine.url)
    
    if db_url.startswith("sqlite"):
        # Extract file path from SQLite URL
        # Format: sqlite:///path/to/file.db or sqlite:///./file.db
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            if db_path.startswith("./"):
                # Relative path - resolve relative to backend directory
                backend_dir = Path(__file__).parent
                db_path = str(backend_dir / db_path[2:])
        else:
            # sqlite:///:memory: or similar
            return  # Skip migrations for in-memory databases
        
        # Get migrations directory
        migrations_dir = Path(__file__).parent / "db" / "migrations"
        
        if migrations_dir.exists():
            # Import and run migration runner
            migration_runner_path = migrations_dir / "migration_runner.py"
            if migration_runner_path.exists():
                # Run migrations using the runner script
                import subprocess
                import sys
                try:
                    result = subprocess.run(
                        [sys.executable, str(migration_runner_path), db_path, str(migrations_dir)],
                        capture_output=True,
                        text=True
                    )
                    if result.returncode == 0:
                        import logging
                        logging.info("Migrations completed successfully")
                        if result.stdout:
                            logging.info(result.stdout)
                    else:
                        import logging
                        logging.warning(f"Migration runner returned non-zero exit code: {result.stderr}")
                except Exception as e:
                    # Log error but don't fail startup
                    import logging
                    logging.warning(f"Migration runner error: {e}")

