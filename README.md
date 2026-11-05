# Rec Metrics

Source for [rec-metrics.com](https://rec-metrics.com): NBA 2K rec box-score stats, player profiles, builds, and the MyNBA league portal.

- `backend/` Flask API (Python, SQLAlchemy)
- `frontend/` React + Vite site
- `discord-bot/` Discord bot that forwards screenshots and league commands to the API
- `docs/` design notes

## How the engines work

- [docs/INGEST.md](docs/INGEST.md): how a box-score screenshot becomes database rows (extraction, checks, dedupe, player matching, cleanup).
- [docs/STATS_ENGINE.md](docs/STATS_ENGINE.md): every stat and metric: leaderboard, Rec Impact Rating, efficiency, profiles, chemistry, AI analysis, admin defensive metrics, and MyNBA standings and awards.

Both list known gaps found in the code.

## What this copy leaves out

This repo is shared for reading, so it won't run end to end as-is:

- **Build planner**: the build-planner service, its data, and `backend/build_service.py` (`app.py` still imports it).
- **MyNBA box-score reader**: `mynba_games.extract_image()` is a stub. Standings, stats, and award races are included.
- Secrets, databases, logs, and deployment config. See the `.env.example` files for the variable names.

## Tests

Most backend tests run on their own against in-memory SQLite or mocks, for example:

```bash
cd backend
python test_mynba_games.py
```
