"""
Sync NBA 2K ratings from nba2kapi.com and seed league rosters from them.

Two jobs, deliberately separate:

  sync_players()        refresh `nba2k_players` (ratings, attributes, badges).
                        Safe to run weekly. Touches no roster.
  seed_league_rosters() create `mynba_players` from the reference data — a
                        setup step, run on purpose, never on a schedule.

The client prefers the authenticated endpoints when NBA2K_API_KEY is set and
falls back to the key-free public list endpoint, which carries every attribute
but returns badges empty.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from name_utils import normalize_name
from mynba_models import MynbaPlayer, MynbaTeam, MynbaTransaction, TXN_IMPORT
from nba2k_models import Nba2kPlayer, Nba2kSyncRun
from mynba_service import player_key, LeagueError

API_BASE = os.getenv("NBA2K_API_BASE", "https://api.nba2kapi.com").rstrip("/")
USER_AGENT = "RecMetrics-MyNBA/1.0 (+https://rec-metrics.com)"
PAGE_LIMIT = 100
REQUEST_PAUSE_S = 0.35  # 500 req/hour on the free key; this is well inside it

# 2K names some franchises differently than we seed them.
API_TEAM_ALIASES = {
    "los angeles clippers": "LAC",   # we seed the official "LA Clippers"
}

# What 2K puts in `team` for an unsigned player.
FREE_AGENT_LABELS = {"", "free agency", "free agent", "free agents"}


class RatingsApiError(Exception):
    pass


def api_key():
    return (os.getenv("NBA2K_API_KEY") or "").strip()


def has_key():
    return bool(api_key())


def _request(path, params=None, method="GET", body=None, timeout=30):
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    key = api_key()
    if key:
        headers["X-API-Key"] = key
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            payload = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = ""
        try:
            body_text = err.read().decode("utf-8")
            parsed = json.loads(body_text)
            detail = (parsed.get("error") or {}).get("message") or body_text[:200]
        except Exception:
            pass
        if err.code == 429:
            raise RatingsApiError(f"Rate limited by nba2kapi. {detail}") from err
        if err.code == 401:
            raise RatingsApiError(
                "nba2kapi rejected the API key. Set NBA2K_API_KEY in backend/.env."
            ) from err
        raise RatingsApiError(f"nba2kapi returned {err.code}. {detail}") from err
    except urllib.error.URLError as err:
        raise RatingsApiError(f"Could not reach nba2kapi: {err.reason}") from err

    if not payload.get("success"):
        message = ((payload.get("error") or {}).get("message")) or "unknown error"
        raise RatingsApiError(f"nba2kapi: {message}")
    return payload


def fetch_players(era="curr"):
    """Every player in an era.

    With a key this is one `/api/players/bulk` call. Without one it pages the
    public endpoint, which returns the same fields but leaves badges empty.
    """
    if has_key():
        payload = _request("/api/players/bulk", {"teamType": era})
        return payload.get("data") or [], True

    players = []
    cursor = None
    while True:
        params = {"teamType": era, "limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        payload = _request("/api/public/players", params)
        batch = payload.get("data") or []
        players.extend(batch)
        pagination = (payload.get("meta") or {}).get("pagination") or {}
        cursor = pagination.get("nextCursor")
        if not pagination.get("hasMore") or not cursor or not batch:
            break
        time.sleep(REQUEST_PAUSE_S)
    return players, False


def fetch_player_detail(slug, era="curr"):
    """Full detail for one player, including badges. Needs a key."""
    if not has_key():
        raise RatingsApiError("Badges need an API key. Set NBA2K_API_KEY in backend/.env.")
    payload = _request(f"/api/players/slug/{urllib.parse.quote(slug)}", {"teamType": era})
    data = payload.get("data")
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _jsonify(value):
    return json.dumps(value) if value not in (None, "", [], {}) else None


def _apply(row, doc, detail=False):
    """Copy an API document onto a row. Returns the overall rating change, if any."""
    before = row.overall

    row.source_id = doc.get("_id") or row.source_id
    row.name = doc.get("name") or row.name
    row.name_key = player_key(row.name)
    row.team = doc.get("team")
    row.team_type = doc.get("teamType") or "curr"
    row.team_img = doc.get("teamImg")
    row.overall = doc.get("overall")
    row.positions = _jsonify(doc.get("positions"))
    row.archetype = doc.get("archetype")
    row.build = doc.get("build")
    row.height = doc.get("height")
    row.weight = doc.get("weight")
    row.wingspan = doc.get("wingspan")
    row.college = doc.get("college")
    row.player_image = doc.get("playerImage")
    row.player_url = doc.get("playerUrl")
    row.game_version = doc.get("gameVersion")
    row.attributes = _jsonify(doc.get("attributes"))
    row.rating_history = _jsonify(doc.get("ratingHistory"))
    row.season_movement = _jsonify(doc.get("seasonMovement"))
    row.source_updated_at = doc.get("lastUpdated")
    row.synced_at = datetime.utcnow()

    # The list endpoint returns `badges: {}`. Never let that erase real badges
    # fetched earlier from the detail endpoint.
    badges = doc.get("badges")
    if badges:
        row.badges = _jsonify(badges)
        if detail:
            row.detail_synced_at = datetime.utcnow()
    elif detail:
        row.detail_synced_at = datetime.utcnow()

    if before is not None and row.overall is not None and before != row.overall:
        return {"from": before, "to": row.overall, "delta": row.overall - before}
    return None


def sync_players(db, era="curr", triggered_by=None):
    """Refresh the ratings reference. Never touches a league roster."""
    run = Nba2kSyncRun(era=era, triggered_by=triggered_by or "manual")
    db.add(run)
    db.flush()

    try:
        docs, authed = fetch_players(era)
    except RatingsApiError as err:
        run.error = str(err)
        run.finished_at = datetime.utcnow()
        db.flush()
        raise

    existing = {
        row.slug: row
        for row in db.query(Nba2kPlayer).filter(Nba2kPlayer.team_type == era).all()
    }

    created = updated = unchanged = 0
    changes = []

    for doc in docs:
        slug = doc.get("slug")
        if not slug:
            continue
        row = existing.get(slug)
        if row is None:
            row = Nba2kPlayer(slug=slug, name=doc.get("name") or slug, name_key="")
            db.add(row)
            existing[slug] = row
            _apply(row, doc)
            created += 1
            continue

        change = _apply(row, doc)
        if change:
            change.update({"name": row.name, "slug": slug})
            changes.append(change)
            updated += 1
        else:
            unchanged += 1

    changes.sort(key=lambda c: abs(c["delta"]), reverse=True)
    run.created = created
    run.updated = updated
    run.unchanged = unchanged
    run.rating_changes = _jsonify(changes[:50])
    run.ok = 1
    run.finished_at = datetime.utcnow()
    db.flush()

    return {
        "era": era,
        "authenticated": authed,
        "total": len(docs),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "changes": changes[:50],
        "badges_available": authed,
        "run_id": run.id,
    }


BADGE_TIERS = ["Bronze", "Silver", "Gold", "Hall of Fame", "Legend"]
BADGE_PAGE_CAP = 100  # the badge-players endpoint's hard limit, and it ignores `cursor`


def fetch_badge_reference():
    """The 40 badges, with category and description."""
    return _request("/api/badges").get("data") or []


def sync_badges(db, era="curr", triggered_by=None, limit=None):
    """Fill in each player's badges.

    Player documents carry `badges: {}` — empty for every current player, with or
    without an API key. The assignments only exist the other way round, on
    `/api/badges/{slug}/players`, which also returns the tier. So this walks the
    40 badges rather than the 650 players.

    That endpoint caps at 100 rows and ignores `cursor`, so we ask per tier to
    stay under the cap. Any tier that still comes back full is reported as
    truncated rather than silently losing players.
    """
    if not has_key():
        raise RatingsApiError("Badges need an API key. Set NBA2K_API_KEY in backend/.env.")

    badges = fetch_badge_reference()
    if limit:
        badges = badges[:limit]

    by_player = {}
    truncated = []
    calls = 0

    for badge in badges:
        slug = badge.get("slug") or badge.get("name")
        if not slug:
            continue
        for tier in BADGE_TIERS:
            try:
                payload = _request(
                    f"/api/badges/{urllib.parse.quote(slug)}/players",
                    {"limit": BADGE_PAGE_CAP, "tier": tier},
                )
            except RatingsApiError as err:
                if "Rate limited" in str(err):
                    raise
                continue
            calls += 1
            rows = payload.get("data") or []
            if len(rows) >= BADGE_PAGE_CAP:
                truncated.append(f"{badge.get('name', slug)} ({tier})")
            for row in rows:
                if row.get("teamType") and row.get("teamType") != era:
                    continue
                player_slug = row.get("slug")
                if not player_slug:
                    continue
                by_player.setdefault(player_slug, []).append({
                    "name": badge.get("name") or slug,
                    "slug": slug,
                    "tier": tier,
                    "category": badge.get("category"),
                })
            time.sleep(REQUEST_PAUSE_S)

    # Highest tier first, then alphabetical — how a player reads their own card.
    # BADGE_TIERS runs weakest to strongest, so reverse it for the sort order.
    order = {tier: i for i, tier in enumerate(reversed(BADGE_TIERS))}
    for entries in by_player.values():
        entries.sort(key=lambda b: (order.get(b["tier"], len(BADGE_TIERS)), b["name"]))

    rows = db.query(Nba2kPlayer).filter(Nba2kPlayer.team_type == era).all()
    now = datetime.utcnow()
    updated = cleared = 0
    for row in rows:
        entries = by_player.get(row.slug)
        if entries:
            row.badges = _jsonify(entries)
            row.detail_synced_at = now
            updated += 1
        elif row.detail_synced_at is not None and not row.badges:
            # Previously marked synced by the old player-detail pass, which never
            # actually returned badges. Clear the flag so status reads honestly.
            row.detail_synced_at = None
            cleared += 1
    db.flush()

    return {
        "badges_checked": len(badges),
        "api_calls": calls,
        "players_with_badges": updated,
        "stale_flags_cleared": cleared,
        "truncated": truncated,
        "total_assignments": sum(len(v) for v in by_player.values()),
    }


# ---------------------------------------------------------------------------
# Seeding league rosters from the reference data
# ---------------------------------------------------------------------------

def seed_league_rosters(db, league, era="curr", actor_discord_id=None, dry_run=False,
                        include_free_agents=True):
    """Create `mynba_players` from the 2K reference data.

    A setup step, not part of the weekly sync. Players whose 2K team matches one
    of the league's 30 franchises land on that roster; everyone else becomes a
    free agent. Existing players are left where the league put them — this never
    moves anyone who is already on a roster.
    """
    reference = db.query(Nba2kPlayer).filter(Nba2kPlayer.team_type == era).all()
    if not reference:
        raise LeagueError(
            "No 2K ratings data yet — run the ratings sync first.", code="no_reference"
        )

    teams = db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id).all()
    lookup = {}
    for team in teams:
        for label in (team.full_name, team.name, team.abbrev):
            if label:
                lookup[normalize_name(label)] = team
    for api_label, abbrev in API_TEAM_ALIASES.items():
        match = next((t for t in teams if t.abbrev == abbrev), None)
        if match:
            lookup[normalize_name(api_label)] = match

    def resolve(api_team):
        label = normalize_name(api_team or "")
        if label in FREE_AGENT_LABELS:
            return None, True   # explicitly a free agent, not a lookup miss
        return lookup.get(label), False

    existing = {
        p.name_key: p
        for p in db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id).all()
    }

    created = linked = skipped_fa = 0
    unmatched_teams = {}

    for ref in reference:
        key = ref.name_key or player_key(ref.name)
        team, declared_fa = resolve(ref.team)

        # Only count a genuine lookup miss — "Free Agency" is an answer, not a gap.
        if team is None and not declared_fa and ref.team:
            unmatched_teams[ref.team] = unmatched_teams.get(ref.team, 0) + 1
        if team is None and not include_free_agents:
            skipped_fa += 1
            continue

        positions = []
        try:
            positions = json.loads(ref.positions) if ref.positions else []
        except (json.JSONDecodeError, TypeError):
            positions = []

        player = existing.get(key)
        if player:
            # Already in the league — refresh the scouting numbers only. Never
            # the roster: that is the league's business, not 2K's.
            player.ovr = ref.overall
            if not player.position and positions:
                player.position = positions[0]
            linked += 1
            continue

        player = MynbaPlayer(
            league_id=league.id,
            name=ref.name,
            name_key=key,
            team_id=team.id if team else None,
            position=positions[0] if positions else None,
            ovr=ref.overall,
        )
        db.add(player)
        existing[key] = player
        created += 1

    summary = {
        "era": era,
        "reference_players": len(reference),
        "created": created,
        "already_in_league": linked,
        "skipped_free_agents": skipped_fa,
        "free_agents": sum(1 for r in reference if normalize_name(r.team or "") in FREE_AGENT_LABELS),
        "unmatched_teams": sorted(unmatched_teams.items(), key=lambda kv: -kv[1]),
        "dry_run": bool(dry_run),
    }

    if dry_run:
        db.rollback()
        return summary

    db.flush()
    db.add(MynbaTransaction(
        league_id=league.id, kind=TXN_IMPORT, player_name="(2K roster seed)",
        actor_discord_id=actor_discord_id,
        note=f"{created} players added from 2K {era} rosters",
    ))
    return summary


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _loads(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def reference_json(ref, full=False):
    if ref is None:
        return None
    payload = {
        "slug": ref.slug,
        "name": ref.name,
        "team": ref.team,
        "team_img": ref.team_img,
        "overall": ref.overall,
        "positions": _loads(ref.positions, []),
        "archetype": ref.archetype,
        "build": ref.build,
        "height": ref.height,
        "weight": ref.weight,
        "wingspan": ref.wingspan,
        "college": ref.college,
        "player_image": ref.player_image,
        "game_version": ref.game_version,
        "synced_at": ref.synced_at.isoformat() if ref.synced_at else None,
    }
    if full:
        payload["attributes"] = _loads(ref.attributes, {})
        payload["badges"] = _loads(ref.badges, {})
        payload["has_badges"] = bool(ref.detail_synced_at)
        payload["rating_history"] = _loads(ref.rating_history, [])
        payload["season_movement"] = _loads(ref.season_movement, [])
    return payload


def sync_run_json(run):
    return {
        "id": run.id,
        "era": run.era,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created": run.created,
        "updated": run.updated,
        "unchanged": run.unchanged,
        "changes": _loads(run.rating_changes, []),
        "ok": bool(run.ok),
        "error": run.error,
        "triggered_by": run.triggered_by,
    }
