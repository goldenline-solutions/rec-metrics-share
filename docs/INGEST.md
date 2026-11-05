# Box-score ingest pipeline

This document explains how an NBA 2K Rec box-score screenshot becomes rows in the database. It covers the Flask backend in `backend/` and the Discord bot in `discord-bot/`. Every claim cites the code it comes from. Where the code is unclear, the document says so.

Short version: a screenshot arrives at `POST /api/ingest`. The backend saves it to disk and hashes it. An OpenAI vision model checks that the image is a 5v5 box score, and a second call extracts the data as strict JSON. The backend runs some sanity checks and may re-extract. It then writes one `Game`, ten `GamePlayer` and `PlayerGameStats` rows, two `TeamTotal` rows and up to ten `Matchup` rows. After the commit it runs two cleanup scripts over the whole database.

## 1. Entry points and auth

All three entry points end at the same Flask route, `POST /api/ingest` (`backend/app.py:436`). That route calls `ingest_box_score` (`backend/app.py:495`, `backend/ingest_service.py:182`).

### HTTP route `/api/ingest`

- The request must be multipart with a `screenshot` file field. Without it the route returns 400 (`backend/app.py:449-454`).
- `season_label` and `mode_label` are optional form fields (`backend/app.py:457-458`). If present, they override the values the model extracted (`backend/ingest_service.py:358-359`).
- **The route does not require auth.** Credentials only decide who gets recorded as the uploader:
  - **Bot token.** The `Authorization` header must equal `Bearer <INGEST_BOT_TOKEN>` or the bare token (`backend/app.py:463-465`). If it matches, the form field `uploader_discord_id` is looked up in `users.discord_id`. On a hit, that user becomes the uploader (`backend/app.py:466-474`).
  - **Session cookie.** If there is no bot match, the `access_token` cookie is checked with `verify_session_token` (`backend/app.py:475-485`).
  - **Neither.** Ingest still runs, with `uploader_user_id=None`.
- The route looks up the user's `platform` and passes it on (`backend/app.py:474,485,502`). `ingest_box_score` then overwrites it (see section 4).
- The web frontend posts with `credentials: 'include'`, so the session cookie is sent (`frontend/src/utils/api.js:65-69`).
- No upload size limit is set: `MAX_CONTENT_LENGTH` does not appear anywhere in `backend/`.

### Discord bot

- The bot only listens in registered channels (`discord-bot/index.js:268`).
  - Someone with Manage Channels registers a channel with `/recmetrics-set-channel`. That command posts to `/api/discord/upload-channels` (`discord-bot/index.js:248-264`).
  - That endpoint requires the bot token (`backend/app.py:338-343`, `backend/app.py:310-320`) and stores one channel per guild (`backend/models.py:466-478`).
  - The bot re-reads the channel list from the API every `CHANNELS_REFRESH_INTERVAL_MS` (`discord-bot/index.js:71-83,199`).
- An attachment counts as an image if its content type starts with `image/` or its name ends in png, jpg, jpeg, webp or gif (`discord-bot/src/ingest.js:19-24`). Every image in the message is queued (`discord-bot/index.js:287-297`).
- The queue is in memory and handles one job at a time (`discord-bot/src/ingest.js:16-17,67-84`). For each job, `runIngest`:
  - downloads the image with a 15 s timeout (`discord-bot/src/ingest.js:28`);
  - posts it as `screenshot` along with `uploader_discord_id` = the message author (`discord-bot/src/ingest.js:33-35`);
  - sends `Authorization: Bearer <API_AUTH_HEADER>` (a `Bearer ` prefix is added if missing), with a 120 s timeout (`discord-bot/src/ingest.js:11-14,37-45`).
- Replies: if `stored` is true, the bot says "ingested". If only `game_id` is present, it says "already in database". On a non-2xx response it replies with an error that includes up to 300 characters of the error message (`discord-bot/src/ingest.js:57-64,77-78`).
- `API_AUTH_HEADER` on the bot must hold the same value as `INGEST_BOT_TOKEN` on the backend. If it is empty, the bot sends no header and the backend ignores `uploader_discord_id`. The upload still succeeds, with no uploader recorded (`backend/app.py:465-466`).

### Batch script

- Run it as `python batch_ingest.py <folder> [--api-url] [--season-label] [--mode-label] [--quiet]` (`backend/batch_ingest.py:205-233`). The default API URL is `http://localhost:5000` (`backend/batch_ingest.py:218`).
- It picks up `.png .jpg .jpeg .gif .webp .bmp` files in sorted order (`backend/batch_ingest.py:12,32-37`).
- Each file is posted to `/api/ingest` with content type `image/png` and a 120 s timeout. **No auth header or cookie is sent**, so every game is stored without an uploader (`backend/batch_ingest.py:60-72`).
- It counts a response as a duplicate when `stored` is false (`backend/batch_ingest.py:155-165`). It exits 1 if any file errored (`backend/batch_ingest.py:247-250`).

## 2. Extraction

All model calls are in `backend/openai_client.py`.

### Model and client

- The model comes from `OPENAI_MODEL` and defaults to `gpt-4o` (`backend/openai_client.py:19`).
- The API key is read when the module is imported. If `OPENAI_API_KEY` is missing, importing the module raises `ValueError` (`backend/openai_client.py:18-22`).
- All calls use Chat Completions with `response_format={"type": "json_schema", "strict": True}` and `temperature=0.0` (`backend/openai_client.py:290-318`, `backend/openai_client.py:450-479`). The docstring at `backend/openai_client.py:388` says "Responses API", but the code calls `client.chat.completions.create`.
- The image is sent inline as a base64 data URL. Its MIME type comes from the file extension and defaults to `image/png` (`backend/openai_client.py:209-231`). The `"detail": "high"` option is commented out (`backend/openai_client.py:461`).

### Call 1: validation (`validate_rec_screenshot`)

- **Schema** (`backend/openai_client.py:33-67`): six booleans and a `reason` string. The booleans are `is_valid_rec_screenshot`, `has_basketball_stats`, `has_player_gamertags`, `has_team_scores`, `has_nba2k_interface` and `is_5v5_game`.
- **Prompt** (`backend/openai_client.py:259-286`): lists the elements a valid screenshot must show, which are a stats table, exactly 5 players per side, two team scores, NBA2K UI, and a 5v5 game. It lists maps, menus, other games, cropped images, 3v3 and 2v2 as invalid. It says AI or CPU players are valid if the total is still 10.
- **Pass rule:** the image passes only if `is_valid_rec_screenshot` is true and all five indicator booleans are true (`backend/openai_client.py:329-338`). On failure, the function builds a reason that names each missing element (`backend/openai_client.py:341-365`).
- **API error:** raises `ValueError("Unable to validate screenshot...")` (`backend/openai_client.py:375-383`). This step is never retried.

### Call 2: extraction (`extract_box_score`)

- Every call to `extract_box_score` runs `validate_rec_screenshot` first. An invalid image raises `ValueError` (`backend/openai_client.py:403-411`).
- **Schema `BOX_SCORE_SCHEMA`** (`backend/openai_client.py:70-206`):
  - `metadata`: season and mode labels, `platform_hint`, `has_platform_icons_before_names` (`:73-90`).
  - `game`: away and home scores, plus `quarters.away` and `quarters.home`, each exactly 4 nullable ints (`:91-118`).
  - `teams`: exactly 2 entries, each with `side` (AWAY or HOME), `grade`, and 13 integer totals: pts, reb, ast, stl, blk, fouls, tov, fgm, fga, tpm, tpa, ftm, fta (`:119-152`).
  - `players`: exactly 10 entries, each with `side`, `row_index` 0-4, `gamertag`, `grade`, and the same 13 stats (`:153-188`).
  - `indicated_matchups`: a nullable array of defender and offender gamertags and sides (`:189-202`).
- **Prompt** (`backend/openai_client.py:417-429`) tells the model to:
  - copy stats and gamertags exactly as shown, including AI names;
  - keep any icon in front of a name, so a name may start with that icon;
  - use 0 for blank cells;
  - fill `indicated_matchups` or set it to null;
  - set `platform_hint` and `has_platform_icons_before_names` based on whether icons appear before names.
- **Feedback mode:** when `validation_feedback` is passed, the prompt gets the error list and a reminder about 10 players with a unique `row_index` per side (`backend/openai_client.py:432-442`).
- `metadata.extracted_from` is always overwritten with `"nba2k_rec_boxscore_screenshot"` (`backend/openai_client.py:485-488`).
- **API-error retry:** if the extraction call raises and `retry_on_error=True` (the default), the function retries once. The retry prompt includes the error text (`backend/openai_client.py:499-546`). If the retry also fails, it raises a plain `Exception("OpenAI extraction failed after retry: ...")` (`backend/openai_client.py:548-549`).

### Checks in `ingest_box_score` after extraction

1. **Structure check, `validate_extraction`** (`backend/utils.py:53-111`):
   - It checks the player count (10), players per side (5 each), unique `row_index` per side, `row_index` range 0-4, the team count (2), and that both AWAY and HOME are present.
   - It returns `False` only when `game`, `teams` or `players` is missing (`backend/utils.py:66-69`). Every other problem is a warning, and the function returns `True` (`backend/utils.py:111`).
   - If it returns `False`, ingest re-extracts once with the warnings as feedback and `retry_on_error=False`. If that also fails, ingest raises `ValueError` (`backend/ingest_service.py:241-270`).
   - Because the strict schema already requires those three keys, this retry path should rarely or never run.
2. **Integrity check, `validate_integrity`** (`backend/utils.py:114-157`):
   - Quarter scores must sum exactly to the final score, for each side.
   - Player points must sum exactly to the team total, for each side. There is no tolerance.
   - Ingest treats warnings containing "player points sum" or "quarter scores sum" as critical. On any critical warning it re-extracts once with those warnings as feedback (`backend/ingest_service.py:274-294`).
   - If critical problems remain after that retry, **the game is still stored**, with a warning added (`backend/ingest_service.py:320-322`).
   - If the retry raises, ingest records the warning "Continuing with original extraction" (`backend/ingest_service.py:329-331`).
3. **Final integrity pass:** runs again after the rows are built and adds only warnings not already in the list (`backend/ingest_service.py:562-571`).

All warnings are returned to the caller in `result["warnings"]` (`backend/app.py:506-507`).

**OpenAI call count per ingest.** The minimum is 2: one validation and one extraction. Each `extract_box_score` call adds its own validation call. The worst case is 7: 3 for the first attempt (validation, extraction, API-error retry), 2 for the structure retry, and 2 for the integrity retry.

### Failure handling

- On any exception inside `ingest_box_score`, it rolls back the session, deletes the saved file, and re-raises (`backend/ingest_service.py:595-603`).
- The route maps errors to HTTP codes (`backend/app.py:524-541`):
  - `ValueError` (invalid screenshot, structure-retry failure, bad `row_index`) returns 400.
  - Any other exception returns 502 if it has a `status_code` attribute, which OpenAI SDK errors do, and 500 otherwise.

## 3. Identity resolution

**The ingest path does not run identity resolution.** `ingest_service.py` imports `resolve_game_players` and `normalize_name` (`backend/ingest_service.py:21-22`), but neither is called anywhere in the file. The live path matches players by exact `players.gamertag` string, as described in section 4.

The code below exists, and this is what it would do.

### Name normalization: `normalize_name` (`backend/name_utils.py:9-61`)

1. Unicode NFKC normalization (`:31`).
2. Removal of 11 zero-width and bidirectional control characters, U+200B through U+202E plus U+FEFF (`:35-49`).
3. Lowercase (`:52`).
4. Trim (`:55`).
5. Collapse runs of whitespace to a single space (`:59`).

`are_names_similar` (`backend/name_utils.py:64-92`) is a separate helper. It returns true for equal names, or when one name contains the other and the length ratio is at least 0.95.

### `find_player_identity` (`backend/identity_resolver.py:51-200`)

1. **Empty name:** returns `(None, None, 'none', 0, False)` (`:82-85`).
2. **Exact match** on `player_name_variants.norm_name`:
   - Increments `seen_count`, updates `last_seen_at`, and returns `'exact'` with confidence 100 (`:88-114`).
   - If an uploader is given, it also looks for that user's `verified` `NameClaim` on the player, filtered by platform if one is given (`:101-112`).
3. **Fuzzy match:**
   - Candidates are up to 200 variants whose `norm_name` starts with the first 3 characters of the detected name, or the whole name if it is shorter (`:118-122`).
   - The score is `rapidfuzz.fuzz.ratio` on a 0-100 scale. If rapidfuzz is not installed, it falls back to `difflib.SequenceMatcher.ratio()*100` (`:12-22,25-48`).
   - **Accept:** top score >= 95 and at least 3 points above the second-best. The function adds a new variant row for the player and returns `'fuzzy'` (`:140-172`).
   - **Ambiguous:** top score >= 95 but within 3 points of the second-best. Returns `(None, None, 'none', score, needs_review=True)` (`:173-175`).
4. **No match:** this includes a best score under 95. The function creates a new `PlayerIdentity` and a first `PlayerNameVariant`, and returns `'none'` with confidence 0 (`:177-200`).

The docstring lists `'variant'` and `'manual'` as possible methods (`:77`). This function never returns either one. `'manual'` is set only by `claims_service` (`backend/claims_service.py:160,243,471,493`).

### `resolve_game_players` (`backend/identity_resolver.py:203-287`)

For each detected name, it calls `find_player_identity`. It then updates the `game_players` row that matches `(game_id, row_index)`, filling `detected_raw_name`, `detected_norm_name`, `player_id_identity`, `claim_id`, `match_confidence`, `match_method` and `needs_review` (`:245-271`). If no row matches, it does nothing (`:272-275`).

### What "unresolved" means

`get_unresolved_games` (`backend/claims_service.py:316-414`) returns `game_players` rows of two kinds:

- `player_id_identity` matches one of the user's verified claims, but `claim_id` is NULL (`:345-375`);
- `needs_review` is true and `claim_id` is NULL, limited to 50 rows (`:377-414`).

Both kinds are filtered to platforms where the user holds claims. A user confirms a row through `confirm_game_player` (`backend/claims_service.py:419`). Because ingest never fills the identity columns, newly ingested games get default values here: NULL for the identity fields and `needs_review=0` (`backend/models.py:91-98`). So new games will not show up as unresolved.

## 4. Storage

Tables are defined in `backend/models.py`. All writes happen in one session that the route opens with `get_db_session()`. That session commits at the end of the `with` block and rolls back on error (`backend/app.py:243-254,493`).

### Order of operations in `ingest_box_score`

1. **Save the file** under `UPLOAD_DIR` (default `./uploads`) as `<uuid4><original extension>` (`backend/app.py:86`, `backend/utils.py:28-50`). Files are kept after a successful ingest, because the delete step is commented out (`backend/ingest_service.py:577-584`).
2. **Hash dedupe.** Compute the SHA-256 of the saved file (`backend/utils.py:11-25`). If any `Game.source_image_sha256` matches, delete the new file and return `stored: False` with the existing game's payload. No OpenAI call is made (`backend/ingest_service.py:211-231`). The column is unique (`backend/models.py:47`).
3. **Extract and check**, as described in section 2.
4. **Content dedupe, `check_duplicate_game`** (`backend/ingest_service.py:103-179`):
   - Candidates are existing games with the same `away_score` and `home_score` (`:145-150`).
   - A candidate counts as a duplicate if its sorted list of `(team_side, position, lowercased gamertag)` matches the new upload's list exactly (`:129-142,165-177`). New names are cleaned with the same steps used at storage time before comparison (`:132-133`).
   - On a match, ingest deletes the file and returns `stored: False` (`backend/ingest_service.py:337-354`). This check runs after the OpenAI calls.
5. **Platform** (`backend/ingest_service.py:362-373`):
   - `count_leading_platform_icons_in_players` counts the names that lose a leading icon when stripped. The game is `"Console"` if that count is **> 4**, and `"PC"` otherwise.
   - The only character treated as an icon is `"0"` (`backend/ingest_service.py:25-36`).
   - The model's `platform_hint` and `has_platform_icons_before_names` appear only in a warning string.
   - The `platform` argument from the route (the user's profile value) is overwritten (`backend/ingest_service.py:373`).
   - `detect_console_platform_from_players`, which uses a threshold of 7 or more names, is defined (`backend/ingest_service.py:69-100`) but never called.
6. **`games`, one row** (`backend/ingest_service.py:379-399`). Stores scores, `away_q1..4` and `home_q1..4`, the source path and hash, platform, `game_version=CURRENT_GAME_VERSION` (`"2K27"`, `backend/models.py:20`) and `uploaded_by_user_id`.
7. **Per player** (`backend/ingest_service.py:405-481`):
   - **Clean the gamertag.** `strip_leading_platform_icons` removes all leading `"0"` characters (`:39-49`). Then `clean_gamertag` removes the 🔊 character and trims (`backend/utils.py:160-176`). Players whose cleaned name is empty are skipped (`:416-417`).
   - **`players`:** looks up the cleaned gamertag with an exact `==` match and inserts a new row if it is not found (`:420-425`). `players.gamertag` is unique (`backend/models.py:67`).
   - **`game_players`:** one row with `team_side`, `position` and `row_index`. The position comes from `row_index`: 0=PG, 1=SG, 2=SF, 3=PF, 4=C. `assign_position` raises `ValueError` for any other value (`backend/utils.py:212-225`). The row also carries the game's platform (`:433-441`).
   - **`player_game_stats`:** one row with `grade` and the 13 stats (`:463-481`).
   - **3PM backfill:** if `tpm` is 0 or None and both `pts > 0` and `fgm > 0`, ingest sets `tpm = pts - 2*fgm - ftm`, clamped to the range 0 to `fgm`, and adds a warning (`:454-462`, `backend/utils.py:179-209`). `tpa` is not changed.
8. **`team_totals`:** one row per entry in `teams`, normally 2 (`backend/ingest_service.py:484-507`).
9. **`matchups`:**
   - Ingest deletes any existing rows for the game, then, for each of the 5 positions where both a HOME and an AWAY player exist, inserts two `POSITIONAL` rows: HOME defending AWAY and AWAY defending HOME. That is at most 10 rows (`backend/ingest_service.py:511-558`).
   - **The model's `indicated_matchups` output is not stored.**
10. **Response payload:** the extracted JSON plus `assigned_position` for each player and the matchups read back from the database (`backend/ingest_service.py:575,606-749`).

### After the commit (route level)

- The in-memory leaderboard cache is cleared (`backend/app.py:509`, `backend/app.py:149-150`).
- If `stored` is true, the route runs `clean_leading_symbols.run(dry_run=False)` and then `fuzzy_merge_players.run(dry_run=False, threshold=88)`. Both run synchronously inside the request, each with its own session, over the **entire** player table. If either one fails, the failure is logged as a warning and the response is still 200 (`backend/app.py:512-520`).

### Tables not written by ingest

Ingest does not write `players_identity`, `player_name_variants` or `name_claims` (`backend/models.py:216-279`). It also leaves the identity columns on `game_players` unset (`backend/models.py:91-98`).

## 5. Cleanup and maintenance scripts

All scripts default to a dry run and only write with `--execute`.

- `backend/clean_leading_symbols.py`:
  - Strips leading **and trailing** characters outside `[a-zA-Z0-9]` (`:26-36`) from `players.gamertag`, the `game_players` detected-name columns, `players_identity`, `player_name_variants` and `name_claims` (`:166-203`).
  - When a cleaned name collides with an existing player, it re-points foreign keys and deletes the duplicate (`:63-138`).
- `backend/fuzzy_merge_players.py`:
  - Compares every pair of players with `fuzz.ratio` on lowercased gamertags, using a default threshold of 88 (allowed range 50-100) (`:113-118,217,229`).
  - Groups transitive matches with union-find (`:43-62`).
  - The winner is the player with the most `game_players` rows (`:164`). The script re-points `game_players`, `player_game_stats`, `matchups` and `player_game_admin_metrics` to the winner (`:73-89`), purges `player_analysis_cache` rows for the losers (`:92-95`), and deletes the losers.
- `backend/run_cleanup.py`: runs `clean_leading_symbols`, then `delete_unused_players`, then `fix_matchup_mismatches`, in that order (`:21-25`).
- `backend/delete_unused_players.py`: deletes players that have no `game_players`, `player_game_stats` or matchup references (`backend/delete_unused_players.py:1-30`).
- `backend/fix_matchup_mismatches.py`: rewrites `POSITIONAL` matchup player IDs to match the current `game_players` row at each position (`backend/fix_matchup_mismatches.py:1-17`).
- `backend/batch_ingest.py`: folder uploader, described in section 1.

## 6. Known gaps and gotchas

Each item below is what the code does as written.

### Auth and inputs

1. **Anyone can ingest.** `/api/ingest` checks no auth and sets no rate or size limit (`backend/app.py:436-503`). Each upload that is not a duplicate costs at least 2 OpenAI calls.
2. **The `OPENAI_API_KEY` check in the route never runs.** `openai_client` raises at import time when the key is missing (`backend/openai_client.py:21-22`), so the check at `backend/app.py:488-489` is never reached.

### Identity and player matching

3. **Identity resolution is not wired in.** See section 3 (`backend/ingest_service.py:21`). `resolve_game_players` would also fail if called:
   - It passes plain SQL strings to `db.execute` (`backend/identity_resolver.py:245-271`). SQLAlchemy is pinned at 2.0.23 (`backend/requirements.txt`), and 2.0 requires `text()` for raw SQL.
   - It uses `?` placeholders, which is SQLite style, while the default engine is PostgreSQL (`backend/db.py:15`).
   - It finds rows by `(game_id, row_index)` without `team_side`, so AWAY and HOME players at the same slot collide (`backend/identity_resolver.py:247-250`).
4. **Players are matched by exact string only.** The lookup is `Player.gamertag == gamertag` (`backend/ingest_service.py:420`), which is case-sensitive on PostgreSQL. The content dedupe, by contrast, lowercases names (`backend/ingest_service.py:139,170`).
5. **Repeated names in one game.** If two players in the same game clean to the same gamertag (for example, two "AI Player" rows), both map to one `Player`. That player then gets two `game_players` and two `player_game_stats` rows for the game. No unique constraint on `(game_id, player_id)` prevents this (`backend/models.py:76-137`). The comment "Unique constraint on (player_id, norm_name)" on `PlayerNameVariant` has no constraint behind it (`backend/models.py:251-254`).

### Platform detection

6. **The "icon" check only looks for the character `"0"`** (`backend/ingest_service.py:33-36`):
   - A real gamertag starting with 0 loses every leading zero (for example, `007x` becomes `7x`) (`backend/ingest_service.py:47-48`).
   - The same check decides PC or Console (`backend/ingest_service.py:367`).
   - The prompt asks the model to keep icons in names (`backend/openai_client.py:420`), but only `"0"` is stripped at ingest. Other icon characters stay until the post-ingest cleanup runs.

### Post-ingest cleanup

7. **Automatic fuzzy merges at threshold 88** run after every stored game, across all players (`backend/app.py:518`).
   - `fuzz.ratio` scores two 10-character names that differ by one substituted character at 90, so such names get merged. Distinct players can be combined this way, including teammates in the same game.
   - The comparison is O(n²) in the number of players, and it runs inside the HTTP request (`backend/fuzzy_merge_players.py:113-118`).
   - The tie-break uses `max(..., key=(count, gamertag.lower()))`, which favors the alphabetically last name. The comment says "alphabetical" (`backend/fuzzy_merge_players.py:163-164`).
8. **`clean_leading_symbols` is ASCII-only.** Names that start or end with a non-ASCII letter lose it (for example, a leading accented letter). Names that are entirely non-ASCII come out empty and are skipped (`backend/clean_leading_symbols.py:26-27,84-86`). Its `merge_player_refs` does not re-point `player_game_admin_metrics` or purge the analysis cache, unlike the fuzzy-merge version (`backend/clean_leading_symbols.py:43-56` vs `backend/fuzzy_merge_players.py:73-95`).

### Checks and retries

9. **Bad data can still be stored.** Most structural problems are warnings only (`backend/utils.py:111`). Critical integrity problems that survive the retry are stored with a warning (`backend/ingest_service.py:320-322`).
10. **The "continuing with original extraction" warning can be wrong.** If the integrity retry's structure check raises, `extracted_data` has already been replaced by the retry result before the exception is caught (`backend/ingest_service.py:290-305,329-331`).
11. **Retry failures can return the wrong status code.** The wrapped exception from the API-error retry (`backend/openai_client.py:549`) has no `status_code`, so the route returns 500 instead of 502 for upstream failures that also fail on retry (`backend/app.py:540`).
12. **The model's matchup output is unused.** `indicated_matchups` is requested from the model, but only positional matchups are stored (`backend/openai_client.py:189-202`, `backend/ingest_service.py:509-558`).

### Dedupe

13. **Content dedupe runs after extraction.** A re-cropped copy of an existing game still costs the OpenAI calls before it is rejected (`backend/ingest_service.py:234,337`).
14. **Cleanup can defeat content dedupe.** The dedupe compares names after only the ingest-time cleaning. If the post-ingest cleanup has since renamed or merged stored players, a later upload of the same game may not match (`backend/ingest_service.py:132-133` vs `backend/app.py:514-518`).

### Other

15. **Upload files are never deleted after a successful ingest** (`backend/ingest_service.py:577-584`).
16. **`.bmp` files are sent to the model under the wrong MIME type.** `batch_ingest` accepts `.bmp` (`backend/batch_ingest.py:12`), but the MIME map has no entry for it, so it is sent as `image/png` (`backend/openai_client.py:223-230`).
17. **Unused setting.** `app.py` reads `DATABASE_URL` (`backend/app.py:89`), but the engine is built from `PG_DATABASE_URL` (`backend/db.py:15`).

## Unclear from the code

- Whether anything outside the files read here calls `resolve_game_players`. A repo-wide grep found only its definition and the unused import.
- How the ORM `db.delete(loser)` in the merge scripts interacts with `Player.game_players` relationships that have no cascade, after the bulk `update(..., synchronize_session=False)` calls. This was not traced.
- Whether the PostgreSQL schema has foreign-key or unique constraints beyond what `models.py` declares. The migrations under `backend/db/migrations/` were not reviewed.
