# NBA2K Rec Box Score Ingestion Pipeline

A production-minded MVP for ingesting NBA2K Rec box score screenshots using OpenAI Vision API to extract structured data and store it in a SQL database.

## Features

- **Screenshot Upload**: Users upload NBA2K Rec box score screenshots
- **AI Extraction**: OpenAI Vision API extracts all visible stats, scores, and player data
- **Structured Storage**: Normalized data stored in SQL database with 6 tables
- **Position Assignment**: Automatic position assignment based on row order (PG→C)
- **Matchup Generation**: Positional matchups automatically generated (PG guards PG, etc.)
- **Idempotency**: SHA256 hashing prevents duplicate ingestions
- **Validation**: Integrity checks with warnings for data inconsistencies

## Tech Stack

- Python 3.11
- Flask (web framework)
- SQLAlchemy ORM (database-agnostic)
- SQLite (default, easy to swap to PostgreSQL)
- OpenAI Python SDK (vision + structured outputs)
- Flask-CORS (for frontend integration)

## Project Structure

```
backend/
├── app.py              # Flask application and routes
├── models.py           # SQLAlchemy database models (6 tables)
├── db.py               # Database engine and session management
├── openai_client.py    # OpenAI API integration with structured outputs
├── ingest_service.py   # Core ingestion business logic
├── utils.py            # Hashing, validation, and helper functions
├── requirements.txt    # Python dependencies
├── uploads/            # Directory for uploaded screenshots
└── README.md           # This file
```

## Setup

### 1. Create Virtual Environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Environment Variables

Create a `.env` file in the `backend/` directory (or set environment variables):

```bash
# Required
OPENAI_API_KEY=your_openai_api_key_here

# Optional (with defaults)
OPENAI_MODEL=gpt-4o                    # Default: gpt-4o
DATABASE_URL=sqlite:///app.db          # Default: sqlite:///app.db
UPLOAD_DIR=./uploads                   # Default: ./uploads
PORT=5000                              # Default: 5000
```

### 4. Initialize Database

The database will be automatically initialized when you run the server. For SQLite, the `app.db` file will be created in the current directory.

### 5. Run the Server

```bash
# From the backend/ directory
python app.py

# Or using Flask's development server
flask --app app run
```

The server will start on `http://localhost:5000` (or the port specified in `PORT`).

## API Endpoints

### Health Check

```bash
GET /health
```

Returns: `{"status": "ok", "message": "NBA2K Rec ingestion API is running"}`

### Ingest Box Score

```bash
POST /api/ingest
Content-Type: multipart/form-data
```

**Form Fields:**
- `screenshot` (required): Image file (PNG, JPG, etc.)
- `season_label` (optional): Season label override
- `mode_label` (optional): Mode label override

**Example using curl:**

```bash
curl -X POST http://localhost:5000/api/ingest \
  -F "screenshot=@path/to/boxscore.png" \
  -F "season_label=Season 5" \
  -F "mode_label=Rec"
```

**Response:**

```json
{
  "game_id": "uuid-string",
  "stored": true,
  "payload": {
    "metadata": {
      "season_label": "Season 5",
      "mode_label": "Rec",
      "extracted_from": "nba2k_rec_boxscore_screenshot"
    },
    "game": {
      "away_score": 85,
      "home_score": 92,
      "quarters": {
        "away": [20, 22, 21, 22],
        "home": [25, 23, 22, 22]
      }
    },
    "teams": [
      {
        "side": "AWAY",
        "grade": "A",
        "totals": { "pts": 85, "reb": 42, ... }
      },
      {
        "side": "HOME",
        "grade": "A+",
        "totals": { "pts": 92, "reb": 45, ... }
      }
    ],
    "players": [
      {
        "side": "AWAY",
        "row_index": 0,
        "gamertag": "PlayerName123",
        "grade": "A",
        "assigned_position": "PG",
        "stats": { "pts": 15, "reb": 5, ... }
      },
      ...
    ],
    "matchups": [
      {
        "defender_gamertag": "HomePlayer1",
        "offender_gamertag": "AwayPlayer1",
        "defender_position": "PG",
        "offender_position": "PG",
        "matchup_type": "POSITIONAL"
      },
      ...
    ]
  },
  "warnings": []  // Optional array of validation warnings
```

**Idempotency:** If you upload the same image (same SHA256 hash), you'll get:

```json
{
  "game_id": "existing-uuid",
  "stored": false,
  "message": "Game already ingested with this image hash",
  "payload": { ... }
}
```

## Database Schema

### Tables

1. **games**: Main game records with scores, quarters, metadata
2. **players**: Master table of unique gamertags
3. **game_players**: Junction table linking games to players with team side and position
4. **player_game_stats**: Individual player statistics per game
5. **team_totals**: Team-level statistics per game
6. **matchups**: Positional matchups between players

All tables use UUID strings as primary keys for better distribution and uniqueness.

## Swapping SQLite to PostgreSQL

The code is database-agnostic thanks to SQLAlchemy. To switch to PostgreSQL:

1. **Install PostgreSQL driver:**

```bash
pip install psycopg2-binary
```

2. **Update DATABASE_URL:**

```bash
# In .env file
DATABASE_URL=postgresql://username:password@localhost:5432/nba2k_db
```

3. **Update requirements.txt** (add `psycopg2-binary==2.9.9`)

4. **Restart the server** - SQLAlchemy will automatically use PostgreSQL.

**Note:** The `db.py` file already handles both SQLite and PostgreSQL connection settings. No code changes needed!

## How It Works

1. **Upload**: User uploads a screenshot via POST `/api/ingest`
2. **Hash Check**: System computes SHA256 hash and checks for existing game (idempotency)
3. **AI Extraction**: OpenAI Vision API extracts structured data using JSON schema strict mode
4. **Validation**: Extracted data is validated (10 players, 5 per side, unique row indices)
5. **Position Assignment**: Positions assigned based on row_index (0=PG, 1=SG, 2=SF, 3=PF, 4=C)
6. **Player Upsert**: Players are upserted by gamertag (create if new, use existing if found)
7. **Data Storage**: Game, players, stats, team totals, and matchups are stored in database
8. **Matchup Generation**: Positional matchups created (HOME PG vs AWAY PG, etc.)
9. **Integrity Checks**: Optional validation warnings (e.g., player points sum vs team total)
10. **Response**: Complete payload returned with game_id and all stored data

## Validation & Warnings

The system performs several validation checks:

- **Structure Validation**: Ensures exactly 10 players (5 per side), unique row indices
- **Integrity Checks** (warnings only):
  - Quarter scores sum equals final score
  - Player points sum equals team total points

Warnings are returned in the response but don't prevent ingestion.

## Error Handling

- **Missing file**: Returns 400 error
- **OpenAI API failure**: Retries once with repair message
- **Validation failure**: Returns 400 error with details
- **Database error**: Transaction rolled back, file cleaned up

## Development Notes

- **CORS**: Enabled for `http://localhost:5173` (common Vite dev server port)
- **File Storage**: Uploaded files saved to `UPLOAD_DIR` (default: `./uploads`)
- **Database**: SQLite file stored at `app.db` (or path in `DATABASE_URL`)
- **Logging**: Set `echo=True` in `db.py` to see SQL queries

## Production Considerations

For production deployment:

1. **Use PostgreSQL** instead of SQLite for better concurrency
2. **Set up proper file storage** (S3, Azure Blob, etc.) instead of local filesystem
3. **Add authentication** to the API endpoints
4. **Implement rate limiting** to prevent abuse
5. **Add monitoring and logging** (e.g., Sentry, CloudWatch)
6. **Use environment-specific configs** (dev/staging/prod)
7. **Set up database migrations** (Alembic) for schema changes
8. **Add health check monitoring** for the `/health` endpoint

## Batch Ingestion

For processing multiple screenshots at once, use the `batch_ingest.py` script:

```bash
# Basic usage - process all images in a folder
python batch_ingest.py /path/to/screenshots

# With optional labels
python batch_ingest.py /path/to/screenshots --season-label "Season 5" --mode-label "Rec"

# Custom API URL (if server is on different host/port)
python batch_ingest.py /path/to/screenshots --api-url http://localhost:5000

# Quiet mode (suppress progress output)
python batch_ingest.py /path/to/screenshots --quiet
```

**Features:**
- Automatically finds all image files (PNG, JPG, JPEG, GIF, WEBP, BMP)
- Processes files in alphabetical order
- Shows progress for each file
- Handles duplicates gracefully
- Provides summary statistics
- Continues processing even if individual files fail

**Example Output:**
```
Scanning folder: ./screenshots
Found 5 image file(s)
------------------------------------------------------------
[1/5] Processing: game1.png
  ✓ Stored as new game: abc123-def456-...

[2/5] Processing: game2.png
  ⊘ Duplicate: Duplicate game found (game_id: xyz789-...)

[3/5] Processing: game3.png
  ✓ Stored as new game: def789-ghi012-...

============================================================
BATCH INGESTION SUMMARY
============================================================
Total files:     5
Processed:       5
Successful:      2 (new games stored)
Duplicates:      1 (already existed)
Errors:          0
============================================================
```

## Troubleshooting

**OpenAI API errors:**
- Verify `OPENAI_API_KEY` is set correctly
- Check that your API key has access to the vision model
- Ensure the model name in `OPENAI_MODEL` is vision-capable (e.g., `gpt-4o`, `gpt-4-vision-preview`)

**"unexpected keyword argument 'proxies'" error:**
- This is usually caused by a version mismatch between `openai` and `httpx` libraries
- Fix by updating dependencies:
  ```bash
  pip install --upgrade openai httpx
  ```
- Or reinstall all requirements:
  ```bash
  pip install --upgrade -r requirements.txt
  ```
- If you have `HTTP_PROXY` or `HTTPS_PROXY` environment variables set, they might cause issues. Unset them if not needed:
  ```bash
  # Windows PowerShell
  $env:HTTP_PROXY = ""
  $env:HTTPS_PROXY = ""
  
  # Linux/Mac
  unset HTTP_PROXY
  unset HTTPS_PROXY
  ```

**Database errors:**
- For SQLite: Ensure write permissions in the directory
- For PostgreSQL: Verify connection string and database exists

**Import errors:**
- Make sure you're running from the correct directory (`backend/`)
- Verify all dependencies are installed: `pip install -r requirements.txt`
- Check that you're using Python 3.11+
- If you get "attempted relative import" errors, make sure you're running `python app.py` from the `backend/` directory

## License

This is an MVP implementation. Adapt as needed for your use case.

