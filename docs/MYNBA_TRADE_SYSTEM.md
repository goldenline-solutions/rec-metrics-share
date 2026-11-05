# MyNBA League Trade System — Design

Status: **built and tested** (2026-09-04). Waiting on the real roster CSV to go live.

Decisions from the admin meeting, all reflected in the code:

| Decision | Answer | What it changed |
|---|---|---|
| Bot logs vs. moves players | **Moves them, after approval** | Full state machine, not a to-do list |
| Spreadsheet | **One-time seed, then the DB owns it** | No Google Sheets sync built — CSV import only |
| Roster size | **11, hard block behind a config flag** | `roster_size` + `enforce_roster_size`, warns by default |
| Salary cap | **Undecided — scaffold it** | Columns and validation exist, dormant behind `enforce_salary_cap` |
| Trade deadline | **Commissioner toggle** | `/trades-lock` |
| Commissioners | **Two or more** | `mynba_commissioners` table; nobody approves their own trade |
| Protest | **League vote** | Approval opens a protest window; rosters move only after it closes |
| Teams | **Real NBA teams, some CPU** | All 30 seeded automatically; CPU teams skip the GM step |
| Command style | **Team names** | `/roster Timberwolves`, `/trade team:Knicks` |
| Player names | **Exact in-game spellings** | Punctuation-insensitive matching ("C.J." == "CJ") |
| Free agency | **Undecided** | `/sign` and `/release` are first-come; no waiver order yet |
| Portal access | **GMs + commissioners only** | Gated server-side, not just in the UI |
| Portal day one | **Rosters, trade buttons, schedule** | Rosters and trades built; schedule needs a data source |

---

## 1. Core principle

**Discord and the website are two front doors. The database is the truth.**

Rosters change in exactly one function — `execute_trade` in `backend/mynba_service.py` —
inside a single transaction with the affected player rows locked. That kills the two bugs
that wreck league bots: a half-applied trade, and two trades executing seconds apart that
both move the same player.

Nothing moves at approval time either. Approval opens a **protest window**; the swap
happens when that window closes. So a successful league protest never has to un-trade
anyone.

---

## 2. Data model

Eight tables, all prefixed `mynba_`. **They do not touch the existing `players` / `games`
tables** — those hold Rec gamertags from screenshots, a completely different domain.

| Table | Purpose |
|---|---|
| `mynba_leagues` | one per Discord server; holds every rule the bot enforces |
| `mynba_teams` | the 30 franchises; `is_cpu` marks the ones with no human GM |
| `mynba_commissioners` | two or more per league |
| `mynba_players` | every player; `team_id IS NULL` means free agent |
| `mynba_trades` | one row per proposal, with its current stage |
| `mynba_trade_assets` | one row per player moving, so N-for-M works |
| `mynba_trade_votes` | one vote per team on a protested trade |
| `mynba_transactions` | append-only history of every roster change |

Status flow:

```
PENDING_GM ──accept──> PENDING_COMMISSIONER ──approve──> APPROVED_WINDOW ──> EXECUTED
                                                              │
                                            protest ──> PROTESTED ──vote──> EXECUTED
                                                                        └─> OVERTURNED
```

Dead ends: `DECLINED`, `VETOED`, `CANCELLED`, `EXPIRED`, and `VOIDED` — the last meaning a
player in the package moved before the trade could execute.

Player names are matched on a normalized key: punctuation dropped, hyphens kept as spaces.
`C.J. McCollum`, `CJ McCollum` and `cj mccollum` are the same person; `Karl-Anthony Towns`
and `Karl Anthony Towns` are too.

---

## 3. API

All under `/api/mynba/`, in `backend/mynba_routes.py`. Two callers, one authorization model:
the bot sends the shared bot token plus `actor_discord_id`; the website sends the normal
session cookie. Either way the backend resolves a Discord id and checks it against the
database. **Discord role checks in the bot are for fast feedback, never for security** — a
forged request or a self-assigned role cannot push a trade through.

| Group | Endpoints |
|---|---|
| Setup | `POST /leagues` · `POST /import` · `POST /commissioners` · `POST /teams/<id>/gm` · `PATCH /league` |
| Read | `GET /me` · `/teams` · `/teams/<id>/roster` · `/players/search` · `/free-agents` · `/trades` · `/transactions` |
| Trade | `POST /trades` · `/trades/<ref>/{accept,decline,cancel,approve,veto,execute,protest,vote,resolve-protest}` |
| Roster | `POST /players/<ref>/{sign,release,move}` |
| Timer | `POST /sweep` — expires stale proposals, executes matured protest windows |

---

## 4. Discord commands

| Command | Who | Does |
|---|---|---|
| `/trade team:<team>` | GM | Opens a box asking who goes each way, then posts the card |
| `/roster [team]` | anyone | A team's roster (defaults to yours) |
| `/player <name>` | anyone | Who has him |
| `/freeagents [position]` | anyone | The free agent pool |
| `/mytrades` | GM | Your pending trades, privately |
| `/sign <player>` · `/release <player>` | GM | Free agency |
| `/league-setup` | admin | Creates the league, seeds all 30 teams |
| `/league-import csv:<file>` | commissioner | Preview first, `apply: True` to write |
| `/team-set-gm team: gm:` | commissioner | Assign a GM, or clear back to CPU |
| `/league-commissioner user:` | commissioner | Add another commissioner |
| `/trades-lock locked:` | commissioner | The deadline switch |

Approvals happen on **buttons attached to the trade card**, not commands. Button ids carry
the trade reference (`mynba:accept:T-0042`), so a bot restart never orphans a pending card.

---

## 5. The approval flow

1. GM A runs `/trade team:Knicks` and fills in who goes each way.
2. The card posts with **Accept / Decline / Withdraw**, pinging GM B.
   *A CPU team has nobody to click, so it skips straight to step 4.*
3. GM B accepts. The card rewrites itself in place: **Approve / Veto**, for commissioners.
4. A commissioner approves — **and nobody has moved yet.** The card becomes
   **Protest / Execute now** and shows a countdown.
5. Any uninvolved GM can protest, which opens a league vote. Otherwise the window closes
   (a 10-minute sweep catches it) and the swap applies.
6. On execution the bot re-checks every player against the roster it locked. If someone
   already moved, the trade is **voided with the reason named** rather than half-applied.

Guards that are in place and tested: you cannot trade a player you do not own, the same
player cannot sit in two open proposals, a proposer cannot approve their own trade, and a
locked league refuses new proposals.

---

## 6. The spreadsheet

Settled at the meeting: the sheet seeds the league once, then the database owns everything
and the portal is where people look. So there is **no ongoing sheet sync** — that whole
chunk of work is gone. `/league-import` reads a CSV, shows a preview, and writes on confirm.

Re-importing later is safe: it matches on player name and updates in place.

---

## 6b. 2K ratings (nba2kapi.com)

**Two tables, kept apart on purpose.**

| Table | Holds | Changed by |
|---|---|---|
| `nba2k_players` | what 2K says — ratings, 35 attributes, badges, headshot | the weekly sync |
| `mynba_players` | what our league says — who is on whose roster | trades, signings, releases |

Joined on a normalized name key. If these were one table, every weekly ratings
refresh would reset every roster and undo every trade. They are not, and there is
a test that proves a re-sync moves nobody.

**Syncing.** `sync_players()` refreshes the reference for the `curr` (modern) era.
With `NBA2K_API_KEY` set it is a single `/api/players/bulk` call; without a key it
pages the public endpoint, which returns every attribute but leaves badges empty.
Badges only exist on the per-player detail endpoint, so `/ratings-badges` walks
players in chunks (~650 calls for a full pass, against a 500/hour limit).

**Weekly, for staff.** The bot checks hourly and syncs once a week, posting an
embed to the approvals channel: how many ratings moved, and the biggest risers and
fallers by name. A restart does not re-fire it.

**Seeding rosters.** `/league-seed-rosters` creates league players from the
reference data — 513 on the 30 franchises, 115 free agents. It previews first.
Re-running it adds nobody and moves nobody; it only refreshes scouting numbers.

Two mapping quirks handled: 2K writes `"Los Angeles Clippers"` where we seed the
official `"LA Clippers"`, and `"Free Agency"` is a team value rather than a blank.

**Player card** at `/league/player/<name>`: all 35 attributes in 2K's six groups
with bars, badges, rating history by game version, bio, and the player's league
transaction history.

**Commands:** `/ratings-sync`, `/ratings-status`, `/ratings-badges`,
`/league-seed-rosters`, `/card <player>`.

---

## 7. What got built

**Backend** (`backend/`)
```
mynba_models.py      8 tables
mynba_service.py     rules, name matching, the trade lifecycle
mynba_routes.py      Flask blueprint, registered in app.py
migrate_mynba.py     creates tables, seeds 30 teams
test_mynba_service.py  35 checks, all passing
```

**Website** (`frontend/src/`)
```
pages/LeaguePage.jsx    Rosters / Trades / Activity, route /league
pages/LeaguePage.css    purple, black and white, scoped to this page only
utils/leagueApi.js      API calls
```

**Bot** (`discord-bot/`) — the old 295-line single file is now wiring only:
```
index.js          client + event routing
src/api.js        authed API client
src/commands.js   12 slash commands
src/buttons.js    trade card buttons
src/embeds.js     card rendering
src/ingest.js     the existing box-score queue, moved unchanged
```

---

## 8. Verified

Backend: 35/35 checks, including the concurrency guard (a trade whose player already moved
voids with the reason named instead of half-applying) and the protest vote.

Website: a full trade driven through the real UI end to end — proposed, accepted, approved,
protest window held with rosters untouched, executed, both moves in the log.

Two bugs found and fixed during that pass:
- Countdowns were 7 hours off. The API sends naive UTC; the browser was reading it as local time.
- "Execute now" called the approve endpoint, which rejects an already-approved trade, so
  nothing moved. Added `POST /trades/<ref>/execute`.

---

## 9. To go live

1. Restart the backend so it serves `/api/mynba/*`.
2. `python migrate_mynba.py --guild <your guild id>` — creates the league, seeds 30 teams.
3. Restart the bot to register the new slash commands.
4. `/league-import csv:<file>` — preview, then `apply: True`.
5. `/team-set-gm` for each human GM. Teams left alone stay CPU.
6. `/league-commissioner` for the second commissioner.

---

## 10. Still open

1. **The nba2kapi key.** Put it in `backend/.env` as `NBA2K_API_KEY=...` — don't paste
   it into chat. Everything works without it except badges.
2. **Free agency rules.** `/sign` is first-come right now. If the league wants a waiver or
   claim order, that is a queue with priority and a deadline — say the word.
3. **Schedule and standings.** You ranked it top-three for the portal, but nothing in the
   system knows the schedule yet. It needs either a manual fixture import or a link to the
   existing Rec game data. Tell me which and I will build it.
4. **Steve's list** of other things worth logging. Each one is roughly one command plus one
   view; knowing them together means one schema instead of four.
