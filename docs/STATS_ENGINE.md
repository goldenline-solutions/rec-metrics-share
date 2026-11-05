# Stats and Metrics Engine: Developer Guide

This covers every place the Flask backend (`backend/`) turns box scores into numbers. It describes what the code does, not what the docstrings say. Where the two disagree, this guide says so.

## 0. Data model and shared helpers

- `Game` (`backend/models.py:24`) holds `home_score`/`away_score`, quarter scores, `platform` ('PC'/'Console') and `game_version` (`backend/models.py:49`, default `CURRENT_GAME_VERSION`).
- Version constants: `LEGACY_GAME_VERSION = "2K26"`, `CURRENT_GAME_VERSION = "2K27"` (`backend/models.py:19-21`).
- `GamePlayer` (`backend/models.py:76`) is one row per player per game. It holds `team_side` (AWAY/HOME), `position` (PG/SG/SF/PF/C), `platform`, `match_confidence` (0-100), `match_method`, and `build_id`.
- `PlayerGameStats` (`backend/models.py:111`) holds the integer box line: pts, reb, ast, stl, blk, fouls, tov, fgm, fga, tpm, tpa, ftm, fta. It has no minutes column.
- `TeamTotal` (`backend/models.py:140`) is the team box line per side.
- A win is always `team_score > opponent_score` for the player's `team_side` (`backend/profile_service.py:79-84`; the leaderboard SQL version is at `backend/app.py:2150-2154`).
- `parse_game_version_param` (`backend/app.py:157-173`): no param means `2K27`; `all` means no filter (None); anything else must be in `GAME_VERSIONS`, or the route returns 400.
- `game_version_clause` (`backend/app.py:176-188`): when filtering on `2K26`, rows with NULL `game_version` are included too. `profile_service.game_version_filter` (`backend/profile_service.py:27-37`) is a copy of the same logic.

## 1. Leaderboard: `GET /api/leaderboard`

Route: `backend/app.py:2106-2268`.

**Inputs (query params, `backend/app.py:2121-2126`)**
- `stat` (default `pts`). Must be one of `pts, reb, ast, stl, blk, fg_pct, tp_pct, ft_pct, games, avg_pts, avg_reb, avg_ast, avg_tpm, avg_tpa, winrate` (`backend/app.py:2130`).
- `limit` (default 20), `min_games` (default 5), `position` (default `ALL`), `platform` (`PC`, `Console`, `ALL`; default `ALL`), `game_version` (default `2K27`).

**Query (`backend/app.py:2156-2197`)**
- Joins Player, PlayerGameStats, GamePlayer (same game and player) and Game.
- It sums pts, reb, ast, stl, blk, fgm, fga, tpm, tpa, ftm and fta, and counts PlayerGameStats rows as `games_played`. Wins are summed with the CASE expression.
- Filters:
  - Position: `GamePlayer.position == position` (`backend/app.py:2183-2184`).
  - Platform: `Game.platform == platform OR GamePlayer.platform == platform` (`backend/app.py:2186-2187`).
  - Version: the version clause (`backend/app.py:2189-2191`).
- Qualification: `HAVING count(PlayerGameStats.id) >= min_games` (`backend/app.py:2193-2195`). The count is taken after the filters, so with `position=PG` a player needs `min_games` games at PG, not in total.

**Formulas (`backend/app.py:2215-2223`).** Each is rounded to 1 decimal, and is 0.0 when the denominator is 0.
- `fg_pct = total_fgm / total_fga * 100`; `tp_pct = total_tpm / total_tpa * 100`; `ft_pct = total_ftm / total_fta * 100`.
  These are pooled percentages: total makes over total attempts, not an average of per-game percentages.
- `winrate = wins / gp * 100`.
- `avg_X = total_X / gp` for X in pts, reb, ast, tpm, tpa.

**Ranking (`backend/app.py:2225-2257`)**
- `pts`, `reb`, `ast`, `stl` and `blk` rank by season totals, not per-game averages. The `avg_*` stats rank by per-game average.
- Sort is descending on `rank_value`, then the list is cut to `limit` and given a 1-based `rank`. Ties have no explicit tiebreak; they keep whatever order SQL returned.

**Caching (`backend/app.py:137-150`)**
- `leaderboard_cache` is a module-level dict with no TTL.
- Key: `f"{stat}|{limit}|{min_games}|{position}|{platform}|{game_version or 'all'}"` (`backend/app.py:140-141`).
- Written at `backend/app.py:2264`. Cleared by `invalidate_leaderboard_cache()` inside `POST /api/ingest` (`backend/app.py:509`), which runs even when the upload was a duplicate. This same dict also holds the RIR and efficiency caches.

## 2. Rec Impact Rating (RIR): `GET /api/analytics/rec-impact-rating`

Route: `backend/app.py:2271-2485`.

**Inputs and filters**
- `min_games` defaults to **10** (`backend/app.py:2285`). The docstring says 5.
- There is no game_version, platform or position filter. It uses every game in the DB across both 2K titles.
- Qualification: `len(GamePlayer rows for player) < min_games` means the player is skipped (`backend/app.py:2310`).
- `games_played = len(game_players)` (`backend/app.py:2326`). Averages divide by this, even for games that have no PlayerGameStats row.
- Cache key `f"rir|{min_games}"` in `leaderboard_cache` (`backend/app.py:2287-2290`, set at `2481`).

**Per-game averages (`backend/app.py:2358-2363`).** `avg_X = total_X / games_played` for pts, ast, stl, blk, reb, tov.

**efficiency_weight (`backend/app.py:2366-2374`)**
```
fg_pct = total_fgm / total_fga * 100    (0 if fga = 0)
tp_pct = total_tpm / total_tpa * 100    (0 if tpa = 0)
ft_pct = total_ftm / total_fta * 100    (0 if fta = 0)
raw = fg_pct * 0.6 + tp_pct * 0.3 + ft_pct * 0.1
efficiency_weight = 0.5 + (raw / 100) * 1.0       # range 0.5 .. 1.5
```

**position_modifier (`backend/app.py:2293-2299`, `2377-2378`)**
- Rebound weights: `PG 0.8, SG 0.9, SF 1.0, PF 1.2, C 1.3`.
- The primary position is the position with the most games (`max` over counts). If there are no stats rows it is `"SF"`; an unknown position gets 1.0.

**Components (`backend/app.py:2381-2387`)**
```
pts_component       = avg_pts * efficiency_weight
ast_component       = avg_ast * 1.25
defensive_component = (avg_stl + avg_blk) * 1.5
reb_component       = avg_reb * position_modifier
tov_penalty         = avg_tov * 1.75
base_rir = pts_component + ast_component + defensive_component + reb_component - tov_penalty
```

**Usage adjustment (`backend/app.py:2391-2411`)**
- Sums `TeamTotal.pts` and `TeamTotal.ast` for the player's side in each game that has a TeamTotal row.
```
avg_team_pts = total_team_pts / total_team_games      (100 if no team totals)
usage_rate = avg_pts / avg_team_pts                   (0.2 if avg_team_pts <= 0)
usage_adjustment = clamp(0.7 + usage_rate * 2.0, 0.7, 1.3)
```

**Final formula (`backend/app.py:2433`)**
```
RIR = ( avg_pts * (0.5 + (0.6*FG% + 0.3*3P% + 0.1*FT%)/100)
      + avg_ast * 1.25
      + (avg_stl + avg_blk) * 1.5
      + avg_reb * position_modifier[primary_position]
      - avg_tov * 1.75 )
      * clamp(0.7 + 2.0 * avg_pts / avg_team_pts, 0.7, 1.3)
```

**Stability Index (`backend/app.py:2415-2430`).** It is returned but not used in RIR.
```
ast_to_ratio      = total_ast / (total_ast + total_tov)
fg_ratio          = total_fgm / total_fga
team_assist_share = min(1.0, avg_ast / avg_team_ast)
stability_index   = ast_to_ratio * fg_ratio * team_assist_share
```

**Output.** Sorted by `rir` descending and ranked 1..N (`backend/app.py:2474-2478`). There is no limit, so every qualified player is returned. Values are rounded at output only (RIR to 2 dp, usage to 3 dp).

## 3. Efficiency analytics: `GET /api/analytics/efficiency`

Route: `backend/app.py:2488-2663`.

**Inputs, filters and caching**
- `min_games` defaults to **10** (`backend/app.py:2503`). The docstring says 5.
- No version, platform or position filter.
- Qualification uses the GamePlayer row count (`backend/app.py:2519`).
- Cache key `f"efficiency|{min_games}"` (`backend/app.py:2505`, set at `2659`).

**Per position played (`backend/app.py:2525-2580`)**
- Games with no Game row or no PlayerGameStats row are skipped.
- For each remaining game it accumulates games, wins/losses, team points, opponent points, player points, team FGM/FGA (from TeamTotal, if present), player FGM/FGA, and plus_minus (`team_score - opponent_score`).

**Per-position output (`backend/app.py:2584-2619`).** Each value is rounded to 1 dp.
- `win_rate = wins / games * 100`.
- `avg_team_points`, `avg_opponent_points`, `avg_player_points` and `avg_plus_minus` are the sums divided by games.
- `team_fg_pct` and `player_fg_pct` are pooled makes over attempts, times 100.
- `team_scoring_efficiency`, `defensive_rating` and `net_rating` are not separate calculations. They are copies of `avg_team_pts`, `avg_opponent_pts` and `avg_plus_minus`.

**Overall output (`backend/app.py:2622-2631`).** The same ratios computed across all positions.

**best_position (`backend/app.py:2634-2639`).** The position with the highest win_rate that has at least 3 games and a win_rate above 0.

**Sort.** Descending `overall_win_rate`, with no rank field and no limit (`backend/app.py:2656`).

## 4. Player profile insights: `GET /api/players/<username>/profile`

Route: `backend/app.py:1969-2013`. Service: `backend/profile_service.py`.

**Identity resolution (`backend/profile_service.py:652-726`)**
- The username is normalized. If a verified `NameClaim` exists, the code collects every Player whose gamertag matches the claim's display name case-insensitively. If there are none, it falls back to a 5-char prefix match plus `normalize_name` equality.
- Without a claim, it uses a case-insensitive gamertag match.
- Games from all matching player IDs are merged.

**Games (`backend/profile_service.py:40-76`)**
- `limit=None`, so this is ALL games newest first, filtered by `game_version` (default 2K27 from the route).

**Summary (`backend/profile_service.py:105-174`)**
- ppg, apg, rpg and toPerGame are total / games (1 dp). fgPct and threePct are pooled.
- `tsPct = pts / (2 * (fga + 0.44 * fta)) * 100` (`backend/profile_service.py:12-19`).

**Trends (`backend/profile_service.py:177-213`)**
- Covers the latest 10 games. Per game: `efficiency = pts + reb + ast + stl + blk - tov` (`backend/profile_service.py:22-24`).

**Insights.** Each one is returned only if its sample gates pass. Thresholds are copied exactly:

| id | min games | rule | file:line |
|---|---|---|---|
| best_when_assists_high | 10 | AST thresholds [3..9]; mean per-game FG% when AST>=t minus when AST<t; both buckets >=5 games; keep largest diff > 1.5 | `backend/profile_service.py:216-252` |
| win_when_shots_high / win_when_tov_low | 15 | FGA thresholds [8,10,12,15], diff > 5; TOV thresholds [2,3,4,5] (TOV<=t), diff > 5; buckets >=5 | `backend/profile_service.py:255-320` |
| weakest_quarter / weakest_stretch | 10 | team quarter avg; needs >=5 games with all 4 quarters non-zero; weakest < strongest - 2. Fallback: last 10 split 5/5, gap > 3 pts | `backend/profile_service.py:323-383` |
| clutch_performer | 15 | close = margin <= 5 (needs >=5), blowout = margin >= 15 | `backend/profile_service.py:386-427` |
| playmaking_wins | 15 | AST thresholds [6..10], win-rate diff > 5 | `backend/profile_service.py:430-465` |
| three_volume_wins | 15 | 3PA thresholds [3,4,5,6], win-rate diff > 5 | `backend/profile_service.py:468-503` |
| wins_vs_losses_scoring | 10 | >=3 wins and >=3 losses; avg pts in W vs L | `backend/profile_service.py:506-538` |
| scoring_consistency | 15 | stdev < 4 means "highly consistent" text | `backend/profile_service.py:541-565` |

- Confidence is "medium" or "low" depending on bucket size (usually >=8 or >=10). No insight ever produces "high".
- `generate_all_insights` sorts by confidence and keeps the top 5 (`backend/profile_service.py:568-608`).
- The share card is the first insight's text, falling back to win rate (if > 50) or PPG (`backend/profile_service.py:611-649`).

**Caching (`backend/app.py:115-135`)**
- In-memory `profile_cache` keyed `f"{username.lower()}|{game_version or 'all'}"` (`backend/app.py:1986`).
- `CACHE_TTL = 10` seconds (`backend/app.py:117`). The comment above it says 60s.
- Nothing invalidates it; it only expires.

## 5. Squad chemistry: `GET /api/players/<username>/chemistry`

Route: `backend/app.py:2016-2038`. The `limit` param defaults to 20 and is capped at 50. Service: `backend/chemistry_service.py:77-196`.

**Constants**
- `MIN_CONFIDENCE = 60` (`:32`), `MIN_GAMES_TOGETHER = 2` (`:35`).
- Junk names: `"AI Player", "AI", "NN", "N/A", "NA", "None", "Player", "Unknown", "-", "--"`, plus any normalized name of length <= 1 (`:39-45`).

**Identity.** Case-insensitive gamertag match, then the prefix + normalize fallback (`:48-66`). It does not check NameClaim, unlike the profile.

**Algorithm**
1. Collect every game the target played and their side in it (first row per game) (`:91-98`).
2. For each other participant in those games, group by `normalize_name(gamertag)`. Skip the target's own names and junk names (`:132-137`).
3. If the participant's row is not confident, increment `lowConfidence` and skip it.
   - Confident means `match_confidence >= 60`. If confidence is NULL, `match_method` must be in `("exact","variant","manual",None)` (`:69-74`).
4. A participant on the same side counts toward `withGames`/`withWins`. One on the opposite side counts toward `vsGames`/`vsWins`. Wins are always from the target's side (`:151-164`).
5. Output:
   - `teammates` are entries with `withGames >= 2`; `rivals` are entries with `vsGames >= 2`.
   - `winRate = round(100 * wins / games, 1)`.
   - Both lists are sorted by `(games, winRate)` descending and cut to `limit` (`:166-196`).

**Filters and caching.** No game_version filter and no caching. `lowConfidence` is counted but never returned.

## 6. AI player analysis: `GET /api/players/<username>/analysis`

Route: `backend/app.py:2041-2103`. Service: `backend/player_analysis_service.py`.

**Model call**
- `client.chat.completions.create(model=OPENAI_MODEL, ..., response_format=json_schema strict, temperature=0.3)` (`backend/player_analysis_service.py:2247-2262`).
- `OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")` (`backend/openai_client.py:19`). The client is OpenAI, not Anthropic.

**Payload build (`build_player_analysis_payload`, `backend/player_analysis_service.py:932-1157`)**
- `last_n` defaults to 25.
- The player is resolved to ONE Player row (`:32-68`). Games are that player_id's newest `last_n` games, with any build joined (`:71-108`). There is no game_version filter and no merging of case variants.
- `meta`: total games, primary position (mode), position distribution, date range, build coverage %, and data-quality flags (missing builds; more than 50% of games with 0 FGA) (`:1109-1120`).
- `per_game`: game id, timestamp, win flag, the full stat line, up to 5 teammates and 5 opponents (gamertag, pts, ast, reb), and a build attribute summary.
  - The comment says "Top 5 by points", but the list is not sorted (`:1029`).
- `aggregates`: totals, per-game averages, splits and trends.
  - Splits (`:1299-1389`): with/without build; by build name (needs >=3 games and >1 build); wins vs losses; FGA >= 10 vs < 10.
  - Trends: last 10 vs all games (`:1392-1421`).
- `derived_metrics` (`:447-621`), computed for overall and last 10:
  - `efg_pct = (fgm + 0.5*tpm) / fga * 100` (`:484`).
  - `ast_to = ast / tov`; equals `ast` when tov = 0 (`:495-498`).
  - `pass_first_index = ast / (fga + ast) * 100` (`:501-505`).
  - `usage_proxy = fga + 0.44*fta + tov` (`:508-511`). This is a total, not per game.
  - `points_per_shot = pts / fga` (`:514-517`).
  - `involvement_proxy = pts + 1.5*ast + 0.7*reb + 1.5*stl + 1.2*blk - 1.3*tov` (`:520-524`). This is also a total.
  - Consistency: mean and stdev of pts, ast, reb and per-game eFG%; needs >= 3 games (`:545-576`).
  - Floor/ceiling: bottom and top 20% of games by per-game involvement; needs >= 5 games (`:579-614`).
- `defensive_matchups` (`:178-329`): opponents the player was the recorded defender of, compared with each opponent's all-time averages. Opponents need >= 3 games (`:149`). Negative values mean good defense.
- `teammate_synergy` (`:682-813`): teammates with >= 5 shared games, top 8. Compares the player's averages with vs without that teammate and ranks by involvement delta.
- `opponent_difficulty` (`:816-921`): opponents with >= 5 games, top 8. Deltas are measured against the player's overall averages.
- `build_impact` (`:1160-1296`): builds with >= 5 games. Gives top 6 attributes, bottom 3 per category, and deltas vs games without that build.
- `claim_candidates` (`:1424-1764`): templated claims, each with evidence.
  - `reliability = 0.6*min(1, n/10) + 0.4*min(1, |effect|/5)` (`:1438-1448`).
  - Thresholds include: AST/TO > 2.0 is a strength and < 1.0 a weakness; eFG% > 55 is a strength and < 45 a weakness; pass-first > 40; synergy delta > 2.0; matchup pts delta > 2.0; build delta > 2.0 (with vs without build > 1.0); defensive pts vs average beyond ±2.0.
  - Sorted by reliability and capped at 40. `low_confidence` is set when reliability < 0.5.

**Prompt (summary).** It is not reproduced here.
- The system prompt (`:1778-1814`) tells the model it is a "NBA 2K26 Rec mode" analyst. It must use only the claim candidates and aggregates, cite a `claim_id` and `sample_size` for every strength, weakness and tendency, say "Not available in dataset" for missing data, and judge stats by position (guards are not expected to rebound, centers are not expected to assist).
- The user prompt (`:1820-1870`) contains:
  - The meta block, claim candidates, defensive matchups, derived metrics, synergy, opponent difficulty and build impact, all as JSON.
  - Per-game averages, splits and trends.
  - The first 10 `per_game` rows.
- The output is a strict JSON schema (`:1993-2244`). Top-level fields:
  - player_summary, strengths, weaknesses, tendencies;
  - synergy, matchups, build_impact, coaching_plan, receipts;
  - data_truthfulness_checks, shareable_card.

**Caching and invalidation (`backend/app.py:2061-2095`)**
- `payload_hash = sha256(json.dumps(payload, sort_keys=True))` (`backend/player_analysis_service.py:2273-2276`).
- Lookup in `PlayerAnalysisCache` (`backend/models.py:383-398`) by `username.lower()`, `last_n` and `payload_hash`, newest first. A hit is returned if it is less than 24 hours old.
- A new game changes the payload and therefore the hash, so the cache invalidates itself in practice. The payload is still rebuilt (every DB query) on every request, even on a cache hit.
- Old rows are never deleted. The only purge is in `fuzzy_merge_players.purge_cache` (`backend/fuzzy_merge_players.py:92-95`), called for merged "loser" gamertags.
- A `ValueError` (player not found) returns 404 (`backend/app.py:2099-2100`).

## 7. Admin defensive metrics: `GET /api/admin/players/<id>/metrics`

**Route.** `backend/app.py:2674-2706`. Admin only. The `last_n` param is optional. Calls `get_player_admin_metrics` (`backend/services/admin_metrics_service.py:754-952`).

**Writer.** `upsert_player_game_admin_metrics(db, game_id)` (`backend/services/admin_metrics_service.py:653-751`) computes one row per player for a game. It raises if the game does not have exactly 10 GamePlayer rows (`:671-672`).

**Config.** `METRICS_CONFIG` at `backend/services/admin_metrics_service.py:45-90`.

**Per player, per game. The stored columns are listed at `backend/models.py:401-433`.**
- `possessions_est = team FGA + 0.44*team FTA + team TOV`, using the player's own team's PlayerGameStats (`:93-126`).
- `team_stl` is the sum of own-team STL; `opp_tov` is the sum of opponent TOV (`:129-169`).
- Build attributes are normalized as `value_current / value_max`, clamped to [0,1]. A missing attribute becomes 0.5 (`:172-197`, `:233-235`).
- `pressure_weight`. With a build:
  `0.45*steal_norm + 0.25*perimD_norm + 0.20*speed_norm + 0.10*position_factor`.
  Without a build it is `position_factor` alone. Position factors: `PG 1.15, SG 1.15, SF 1.00, PF 0.90, C 0.80` (`:200-245`).
- `pressure_share = pressure_weight / sum(team pressure_weights)` (`:564-569`).
- `unattributed_tov = max(0, opp_tov - team_stl)` (`:572`).
- `tov_forced_est = unattributed_tov * pressure_share` (`:575`).
- `onball_ratio_est`:
  - Base by position: `PG 0.65, SG 0.65, SF 0.50, PF 0.40, C 0.35`.
  - Add `+0.05` if perimD_norm >= 0.85; add `-0.05` if block_norm >= 0.85.
  - Clamp to [0.2, 0.8] (`:248-288`).
- `onball_pressure_est = tov_forced_est * onball_ratio_est`; `offball_disruption_est = tov_forced_est * (1 - onball_ratio_est)` (`:581-582`).
- `disruption_score = 1.0*stl + 0.7*blk + 0.6*tov_forced_est + (-0.6)*fouls` (`:585-590`).
- `disruption_score_100 = disruption_score / possessions_est * 100` (`:593-596`).
- `matchup_stop` (`:388-523`), for each opponent the player is recorded as guarding who took at least 1 FGA:
  - Weight is the opponent's FGA.
  - `fg_delta = opp FG% this game - baseline FG%`.
  - `matchup_stop = sum(-fg_delta * weight) / sum(weight)`.
  - `matchup_stop_per100 = matchup_stop / possessions_est * 100`.
- Baseline FG% (`:291-385`), tried in this order:
  - The opponent's last 15 prior games (`MATCHUP_BASELINE_LAST_N_GAMES`), if they total >= 10 FGA.
  - Otherwise the last 150 position rows, if they total >= 50 FGA.
  - Otherwise 0.5.
- `stocks_per100 = (stl + blk) / possessions_est * 100` (`:604-608`).
- `def_disruption_per100`:
  - `0.7*matchup_stop_per100 + 0.3*stocks_per100`, when there is at least one matchup and `matchup_stop_per100 != 0`.
  - Otherwise it equals `disruption_score_100` (`:612-624`).
- Flags stored: `used_build`, `used_matchup_baseline`, `used_matchup_primary`.

**Reader aggregates (`:868-947`)**
- Windows: last_5, last_10 and last_25 (taken from the `last_n`-limited list), plus all_time (every row for the player).
- Each window gets means of per-100 values (tov_forced, on/off ball, steals, blocks, fouls, disruption_score_100), total possessions, and matchup means when present.

**How rows get written.** Only `backend/scripts/backfill_admin_metrics.py:17-56`, which loops over every Game, calls the upsert, and logs and skips any game that fails.

## 8. MyNBA league (`backend/mynba_games.py`)

**Routes**
- `GET /api/mynba/standings` returns standings plus award races (`backend/mynba_routes.py:1160-1170`).
- `GET /api/mynba/stats` returns player rows (`backend/mynba_routes.py:1173-1179`). The blueprint prefix is set at `backend/mynba_routes.py:35`.
- Both are member- or bot-only.
- Everything is recomputed on every read; there is no cache (`backend/mynba_games.py:11-13`).

**Standings (`backend/mynba_games.py:383-435`)**
- Games are processed in `played_on, created_at` order. Only teams in the league are counted.
- Per team: W, L, PF, PA, home/away record, `pct = w/gp` (3 dp), ppg, oppg, `diff = (pf - pa)/gp` (1 dp), last 10, and streak (the length of the trailing run of the last result).
- Teams are grouped by `conference` (NULL becomes "League").
- Sort and tiebreaks (`:428`): `pct` desc, then `w` desc, then `diff` desc (None counts as 0), then team `name` asc. There is no head-to-head tiebreak.
- `GB = ((lead.w - w) + (l - lead.l)) / 2`, where the lead is the first-sorted team in the conference. It shows "-" when the result is 0 (`:431-432`).

**Game Score (`backend/mynba_games.py:438-442`).** This is Hollinger's formula, applied to season totals:
```
GS = pts + 0.4*fgm - 0.7*fga - 0.4*(fta - ftm) + 0.7*oreb + 0.3*(reb - oreb)
     + stl + 0.7*ast + 0.7*blk - 0.4*fouls - tov
game_score (per game) = round(GS(totals) / gp, 1)        # backend/mynba_games.py:503
```

**Player rows (`backend/mynba_games.py:445-506`)**
- Key is `player_id`, or `"{player_name}|{team_id}"` for unlinked box names (`:468`).
- Starters are the top 5 in minutes per team per game; everyone else counts as a bench game (`:466`).
- `team_id` is the latest team the player appeared for (`:475`). `team_win_pct` and `team_games` come from that team (`:485`, `:497`).
- Rows are sorted by per-game pts desc, then name.

**Award races (`backend/mynba_games.py:509-543`)**
- Qualification is `gp >= ceil(team_games / 2)`, and team_games must be non-zero (`:519-520`).
- Formulas:
  - MVP: `game_score * (0.6 + 0.8 * team_win_pct)`, which is x1.0 at .500 (`:536`).
  - DPOY: `2*stl_pg + 2*blk_pg + 0.5*(reb_total - oreb_total)/gp` (`:537-538`).
  - ROY: `game_score`, players with `is_rookie` (`:539`).
  - SMOY: `game_score`, players where `bench_games * 2 > gp` (`:540`).
- Top 5 per race, by score desc (`:542`).

**Soft checks (`backend/mynba_games.py:270-298`).** Each produces a warning only.
- Minutes should total `240 + 25*(periods - 4)`, within ±2.
- Player points should sum to the team score.
- Each player's points should equal `2*fgm + tpm + ftm`.

## 9. Site counters: `GET /api/stats`

`backend/app.py:373-385` returns `games_tracked = count(Game)` and `players_tracked = count(Player)`. It applies no filters and no cache. Player rows include AI or junk names and case variants that have not been merged.

## 10. Known gaps and gotchas

1. **Stale leaderboard, RIR and efficiency caches.** `invalidate_leaderboard_cache()` is called only from `/api/ingest` (`backend/app.py:509`). Other writes do not clear it, so the cached numbers stay wrong until the next upload or a restart. Those writes are:
   - `PUT /api/games/<id>` and `DELETE /api/games/<id>` (`backend/app.py:856`, `1111`);
   - claims, build assignment, and fuzzy merges run outside ingest.
2. **Cache scope and growth.** The cache is a per-process dict, so with several worker processes each one has its own copy and only the worker that handled the ingest is cleared. I could not find a worker config in the repo. The key includes the free-form `limit` and `min_games`, so the dict can grow without bound.
3. **Inconsistent filtering.** Leaderboard and profile filter by game_version (default 2K27). RIR, efficiency, chemistry, AI analysis and admin metrics mix 2K26 and 2K27, and none of them filter by platform.
4. **Leaderboard ranks raw totals** for `pts/reb/ast/stl/blk`, which rewards volume of games. Use the `avg_*` stats for per-game ranking. There is no `avg_stl`/`avg_blk`.
5. **Defaults differ from docs.** RIR and efficiency default `min_games` to 10 while their docstrings say 5. `CACHE_TTL` is 10s while the comment says 60s.
6. **The RIR usage comment is wrong.** The comment maps usage 0.15 to x0.7 and 0.35 to x1.3. The code gives 0.15 → 1.0 and clamps at 1.3 for any usage >= 0.30. The 0.7 floor is reached only at usage 0 (`backend/app.py:2409-2411`).
7. **RIR and efficiency are N+1 queries.** They loop over every Player with per-game queries (`backend/app.py:2303-2404`, `2512-2580`), so the first uncached request scales with the size of the whole DB.
8. **RIR denominators.** RIR divides by the GamePlayer count, so a game with no stats row lowers every average. Qualification also counts GamePlayer rows, not stats rows.
9. **Analysis identity differs from profile.** The profile merges all case variants and claim matches. The analysis uses a single Player row (`backend/player_analysis_service.py:32-68`, `:71-108`), so the two can describe different sets of games.
10. **Analysis cache keys.** Rows are keyed on `username.lower()`, but the payload hash includes the raw `meta.username`, so `Foo` and `foo` create separate cache rows. `fuzzy_merge_players.purge_cache` deletes by the un-lowercased gamertag (`backend/fuzzy_merge_players.py:93-94`), so it misses rows for mixed-case names. Cache rows are never pruned.
11. **Key mismatches in derived metrics.** Floor/ceiling `key_differences` and the "trend" claims look up `pts`, `ast`, `reb` and `tov`. `compute_metrics_for_games` only emits `avg_pts`, `avg_ast` and `avg_reb`, and has no tov key (`backend/player_analysis_service.py:527-532`, `:610`, `:1529`). Only the `efg_pct` and `ast_to` branches can ever fire.
12. **The AI prompt hard-codes "NBA 2K26"** (`backend/player_analysis_service.py:1778`, `:1820`) even though new games are 2K27.
13. **Gamertags go to OpenAI.** Other players' gamertags are sent in `team_context`, synergy and opponent blocks.
14. **The strict schema may be invalid.** `receipts` and `data_truthfulness_checks` are top-level properties but are not in `required` (`backend/player_analysis_service.py:2239-2242`) while `strict: True` is set. As far as I know OpenAI strict mode requires every property to be listed, so this could make the call fail. I have not checked this against a live call.
15. **Admin metrics are never computed on ingest.** `upsert_player_game_admin_metrics` is imported in `backend/app.py:43` but never called there. The `POST /api/admin/games/<id>/recompute-admin-metrics` route mentioned in the service docstring (`:30-31`) does not exist. New games have no admin metrics until someone runs the backfill script by hand.
16. **Admin metric details**
    - The `MATCHUP_MIN_WEIGHT` (0.1) check never filters anything, because FGA=0 rows are already skipped.
    - The flag named `FALLBACK_TO_TOV_MODEL` actually gates the use of the matchup model (`:612`), so setting it to False turns matchups off.
    - `matchup_stop_per100` divides a FG% delta by the defender's *own* team possessions.
    - An attribute whose normalized value is 0.0 is replaced by 0.5, because the code uses `or 0.5`.
    - The model comment says "Unique constraint", but no unique constraint is declared on (game_id, player_id) (`backend/models.py:439-442`).
17. **MyNBA award details**
    - A traded player's team win % and qualification use only their latest team's games (`backend/mynba_games.py:475`, `:497`).
    - Unlinked box names can appear in the MVP, DPOY and SMOY races (but not ROY).
    - `team_wins` credits the home team on any non-away-win, which is safe only because ties are rejected at save time (`backend/mynba_games.py:262-263`, `:456`).
18. **Profile insight confidence never reaches "high"**, so the confidence sort is effectively medium before low.
    - In `generate_insight_win_rate_threshold`, a negative shot-volume diff still raises `best_diff` without setting an insight. That can suppress a valid turnover insight (`backend/profile_service.py:281-290`).
    - The "based on last N games" notes actually cover all games in the version.
