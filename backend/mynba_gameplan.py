"""
Weekly gameplans: coaching settings, rotation minutes, the weekly lock, and
the commissioner's "change this in 2K" feed.

What a GM may set, and to what, comes from mynba_gameplan_options.json — the
catalog the commissioner checked against the game. Add a setting there, not here.

Every save diffs the old plan against the new one and records each changed
field in mynba_gameplan_changes. The commissioner works that list in 2K and
marks rows done; nothing in 2K changes on its own.
"""
import json
import os
import re
from datetime import datetime

from mynba_models import MynbaGameplan, MynbaGameplanChange, MynbaPlayer
from mynba_service import LeagueError
# The weekly lock lives in mynba_schedule so the trade code can use it too.
from mynba_schedule import lock_status, iso as _iso

CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mynba_gameplan_options.json")

# 2K constants, not league choices.
TEAM_MINUTES = 240
MAX_PLAYER_MINUTES = 48
STARTER_SLOTS = ("PG", "SG", "SF", "PF", "C")

# Sections whose GM-set entries make up a gameplan. Rotation is handled apart.
GAMEPLAN_SECTIONS = ("coaching", "emphasis")


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

_catalog_cache = {"mtime": None, "data": None}


def load_catalog():
    """The options file, re-read when it changes on disk."""
    mtime = os.path.getmtime(CATALOG_PATH)
    if _catalog_cache["mtime"] != mtime:
        with open(CATALOG_PATH, encoding="utf-8") as fh:
            _catalog_cache["data"] = json.load(fh)
        _catalog_cache["mtime"] = mtime
    return _catalog_cache["data"]


def gameplan_fields():
    """Settings a GM submits each week, in display order, keyed by setting key."""
    catalog = load_catalog()
    section_order = {s["key"]: s.get("order", 99) for s in catalog["sections"]}
    fields = [
        s for s in catalog["settings"]
        if s["section"] in GAMEPLAN_SECTIONS and s.get("setBy") == "gm"
    ]
    fields.sort(key=lambda s: (section_order.get(s["section"], 99), s.get("order", 99)))
    return {f["key"]: f for f in fields}


def options_json(league):
    """Everything the gameplan form needs to render, including this league's rules."""
    catalog = load_catalog()
    fields = gameplan_fields()
    return {
        "sections": [s for s in catalog["sections"] if s["key"] in GAMEPLAN_SECTIONS],
        "fields": [
            {
                "key": f["key"], "section": f["section"], "label": f["label"], "kind": f["kind"],
                "min": f.get("min"), "max": f.get("max"),
                "options": [o["name"] for o in f.get("options", [])] if f["kind"] == "choice" else None,
            }
            for f in fields.values()
        ],
        "rules": rotation_rules(league),
    }


def rotation_rules(league):
    return {
        "team_minutes": TEAM_MINUTES,
        "max_player_minutes": MAX_PLAYER_MINUTES,
        "starter_slots": list(STARTER_SLOTS),
        "sixth_man_min": league.sixth_man_min_minutes,
        "bench_min": league.bench_min_minutes,
        "roster_size": league.roster_size,
        "untouchables_per_team": league.untouchables_per_team,
        # Starters must be listed at their slot, as primary or secondary position.
        "starters_in_position": True,
    }


# ---------------------------------------------------------------------------
# Reading a plan
# ---------------------------------------------------------------------------

def get_gameplan(db, league, team):
    return db.query(MynbaGameplan).filter(MynbaGameplan.team_id == team.id).first()


def _loads(text, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def slot_label(index):
    if index < len(STARTER_SLOTS):
        return STARTER_SLOTS[index]
    if index == len(STARTER_SLOTS):
        return "6th man"
    return f"Bench {index + 1}"


def gameplan_json(db, league, team, plan=None, viewer_can_edit=False):
    """The plan plus the current roster, with every rostered player in the rotation list.

    Players who left the team since the last save drop out; new arrivals are
    appended at 0 minutes so the GM sees them.
    """
    plan = plan if plan is not None else get_gameplan(db, league, team)
    settings = _loads(plan.settings, {}) if plan else {}
    saved_rotation = _loads(plan.rotation, []) if plan else []

    roster = (db.query(MynbaPlayer)
              .filter(MynbaPlayer.league_id == league.id, MynbaPlayer.team_id == team.id)
              .order_by(MynbaPlayer.ovr.desc().nullslast(), MynbaPlayer.name)
              .all())
    by_id = {p.id: p for p in roster}

    rotation, seen, departed = [], set(), []
    for entry in saved_rotation:
        player = by_id.get(entry.get("player_id"))
        if not player:
            departed.append(entry.get("player_name") or entry.get("player_id"))
            continue
        seen.add(player.id)
        rotation.append(_rotation_row(player, entry.get("minutes", 0), len(rotation)))
    for player in roster:
        if player.id not in seen:
            rotation.append(_rotation_row(player, 0, len(rotation)))

    total = sum(r["minutes"] for r in rotation)
    problems = rotation_problems(league, [(by_id[r["player_id"]], r["minutes"]) for r in rotation]) if plan else []
    if departed:
        problems.insert(0, f"No longer on the roster: {', '.join(departed)}. Re-save the rotation.")

    return {
        "team_id": team.id,
        "team": team.name,
        "settings": settings,
        "rotation": rotation,
        "total_minutes": total,
        "problems": problems,
        "version": plan.version if plan else 0,
        "submitted": plan is not None,
        "updated_at": _iso(plan.updated_at) if plan else None,
        "updated_by": plan.updated_by_name if plan else None,
        "can_edit": viewer_can_edit,
    }


def _rotation_row(player, minutes, index):
    return {
        "player_id": player.id,
        "name": player.name,
        "position": player.position,
        "secondary_position": player.secondary_position,
        "ovr": player.ovr,
        "is_untouchable": bool(player.is_untouchable),
        "minutes": int(minutes or 0),
        "slot": slot_label(index),
        "out_of_position": out_of_position(player, index),
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def clean_settings(raw):
    """Check submitted settings against the catalog; returns canonical values.

    A value of None clears that setting. Choice matching ignores case and
    returns 2K's exact spelling.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise LeagueError("Settings must be an object of setting → value.", code="bad_settings")
    fields = gameplan_fields()
    out = {}
    for key, value in raw.items():
        field = fields.get(key)
        if not field:
            raise LeagueError(f'"{key}" isn\'t a gameplan setting.', code="bad_settings")
        if value is None or value == "":
            out[key] = None
            continue
        if field["kind"] == "slider":
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise LeagueError(f"{field['label']} needs a whole number.", code="bad_settings")
            lo, hi = field.get("min", 0), field.get("max", 100)
            if not lo <= number <= hi:
                raise LeagueError(f"{field['label']} must be between {lo} and {hi}.", code="bad_settings")
            out[key] = number
        elif field["kind"] == "choice":
            names = {o["name"].lower(): o["name"] for o in field.get("options", [])}
            match = names.get(str(value).strip().lower())
            if not match:
                raise LeagueError(f'"{value}" isn\'t an option for {field["label"]}.', code="bad_settings")
            out[key] = match
        else:
            raise LeagueError(f"{field['label']} can't be set in a gameplan.", code="bad_settings")
    return out


def listed_positions(player):
    """Every position a player is listed at: primary plus secondary, e.g. {"PF", "C"}."""
    out = set()
    for raw in (getattr(player, "position", None), getattr(player, "secondary_position", None)):
        for part in re.split(r"[/,\s]+", (raw or "").upper()):
            if part:
                out.add(part)
    return out


def out_of_position(player, slot_index):
    """True when a starter isn't listed at the slot they start in. Unknown positions pass."""
    if slot_index >= len(STARTER_SLOTS):
        return False
    listed = listed_positions(player)
    return bool(listed) and STARTER_SLOTS[slot_index] not in listed


def rotation_problems(league, entries):
    """Rule breaks in a rotation, as sentences.

    `entries` is [(player, minutes)] in slot order; `player` needs name,
    position and secondary_position (a MynbaPlayer or a dict-like stand-in).
    """
    problems = []
    for i, (player, _) in enumerate(entries[:len(STARTER_SLOTS)]):
        if out_of_position(player, i):
            listed = "/".join(sorted(listed_positions(player)))
            problems.append(f"{player.name} is listed {listed} and can't start at {STARTER_SLOTS[i]}.")
    total = sum(m for _, m in entries)
    if total != TEAM_MINUTES:
        diff = TEAM_MINUTES - total
        problems.append(
            f"Minutes add up to {total}, not {TEAM_MINUTES} — "
            f"{'add' if diff > 0 else 'remove'} {abs(diff)}."
        )
    six = len(STARTER_SLOTS)
    if len(entries) > six and entries[six][1] < league.sixth_man_min_minutes:
        problems.append(f"6th man needs at least {league.sixth_man_min_minutes} minutes (has {entries[six][1]}).")
    for i in range(six + 1, min(len(entries), league.roster_size or 8)):
        if entries[i][1] < league.bench_min_minutes:
            problems.append(f"{slot_label(i)} needs at least {league.bench_min_minutes} minutes (has {entries[i][1]}).")
    return problems


def clean_rotation(db, league, team, raw):
    """Validate a submitted rotation and return it in storage form.

    Order is slot order: first five start at PG, SG, SF, PF, C; sixth is the
    6th man. Rostered players left out are appended at 0 minutes.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise LeagueError("Rotation must be a list of players in slot order.", code="bad_rotation")

    roster = db.query(MynbaPlayer).filter(
        MynbaPlayer.league_id == league.id, MynbaPlayer.team_id == team.id).all()
    by_id = {p.id: p for p in roster}

    entries, seen = [], set()
    for item in raw:
        pid = (item or {}).get("player_id")
        player = by_id.get(pid)
        if not player:
            raise LeagueError("A player in the rotation isn't on this roster. Reload and try again.",
                              code="bad_rotation")
        if pid in seen:
            raise LeagueError(f"{player.name} is in the rotation twice.", code="bad_rotation")
        seen.add(pid)
        try:
            minutes = int(item.get("minutes") or 0)
        except (TypeError, ValueError):
            raise LeagueError(f"{player.name}'s minutes need to be a whole number.", code="bad_rotation")
        if not 0 <= minutes <= MAX_PLAYER_MINUTES:
            raise LeagueError(f"{player.name}'s minutes must be 0–{MAX_PLAYER_MINUTES}.", code="bad_rotation")
        entries.append((player, minutes))

    for player in sorted(roster, key=lambda p: (-(p.ovr or 0), p.name)):
        if player.id not in seen:
            entries.append((player, 0))

    problems = rotation_problems(league, entries)
    if problems:
        raise LeagueError(" ".join(problems), code="bad_rotation", extra={"problems": problems})

    return [{"player_id": p.id, "player_name": p.name, "minutes": m} for p, m in entries]


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def save_gameplan(db, league, team, settings=None, rotation=None, actor=None,
                  is_commissioner=False, base_version=None, now_utc=None):
    """Validate, store, and log a gameplan edit. Returns (plan, changes).

    `settings` merges into what's saved; `rotation` replaces it. Either may be
    left out. GMs are blocked while the gameplan is locked; commissioners never are.
    """
    if not is_commissioner and lock_status(league, now_utc)["locked"]:
        raise LeagueError(
            "Gameplans are locked until after the sim. Ask a commissioner if something has to change.",
            code="locked",
        )

    new_settings = clean_settings(settings)
    new_rotation = clean_rotation(db, league, team, rotation)

    plan = get_gameplan(db, league, team)
    if plan and base_version is not None and int(base_version) != plan.version:
        who = f" by {plan.updated_by_name}" if plan.updated_by_name else ""
        raise LeagueError(
            f"This gameplan was changed{who} after you opened it. Reload to see the latest, then redo your edit.",
            code="stale",
        )
    if not plan:
        plan = MynbaGameplan(league_id=league.id, team_id=team.id, version=0)
        db.add(plan)

    old_settings = _loads(plan.settings, {})
    old_rotation = _loads(plan.rotation, [])

    merged = dict(old_settings)
    if new_settings:
        for key, value in new_settings.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
    final_rotation = new_rotation if new_rotation is not None else old_rotation

    diffs = _settings_diff(old_settings, merged) + _rotation_diff(db, old_rotation, final_rotation)
    if not diffs and plan.version > 0:
        return plan, []

    plan.settings = json.dumps(merged)
    plan.rotation = json.dumps(final_rotation)
    plan.version = (plan.version or 0) + 1
    plan.updated_by_discord_id = actor.discord_id if actor else None
    plan.updated_by_name = actor.display_name if actor else None
    db.flush()

    changes = [_record_change(db, league, team, actor, is_commissioner, *d) for d in diffs]
    db.flush()
    return plan, [c for c in changes if c is not None]


def _settings_diff(old, new):
    fields = gameplan_fields()
    out = []
    for key, field in fields.items():
        before, after = old.get(key), new.get(key)
        if before != after:
            out.append((key, field["label"], _fmt(before), _fmt(after)))
    return out


def _rotation_diff(db, old, new):
    def index(rows):
        # 0 minutes means out of the rotation; where a DNP sits in the list doesn't matter in 2K.
        return {r["player_id"]: (i, r.get("minutes", 0), r.get("player_name"))
                for i, r in enumerate(rows) if r.get("minutes")}

    before, after = index(old), index(new)
    out = []
    # Walk in the new slot order, then anyone who only appears in the old one.
    order = [r["player_id"] for r in new if r["player_id"] in after] +         [r["player_id"] for r in old if r["player_id"] in before and r["player_id"] not in after]
    for pid in order:
        b, a = before.get(pid), after.get(pid)
        old_txt = f"{b[1]} min · {slot_label(b[0])}" if b else "Out of rotation"
        new_txt = f"{a[1]} min · {slot_label(a[0])}" if a else "Out of rotation"
        if old_txt != new_txt:
            name = (a or b)[2] or pid
            out.append((f"rotation:{pid}", name, old_txt, new_txt))
    return out


def _fmt(value):
    return None if value is None else str(value)


def _record_change(db, league, team, actor, is_commissioner, key, label, old, new):
    """Add a feed row, or fold into the open one for the same field."""
    open_row = db.query(MynbaGameplanChange).filter(
        MynbaGameplanChange.team_id == team.id,
        MynbaGameplanChange.field_key == key,
        MynbaGameplanChange.done_at.is_(None),
    ).first()

    if open_row:
        if open_row.old_value == new:
            # Changed back to what 2K already has: nothing left to do.
            db.delete(open_row)
            return None
        open_row.new_value = new
        open_row.field_label = label
        open_row.actor_discord_id = actor.discord_id if actor else None
        open_row.actor_display_name = actor.display_name if actor else None
        open_row.by_commissioner = bool(is_commissioner)
        # Re-announce the updated value.
        open_row.notified_at = None
        return open_row

    row = MynbaGameplanChange(
        league_id=league.id, team_id=team.id, team_name=team.name,
        field_key=key, field_label=label, old_value=old, new_value=new,
        actor_discord_id=actor.discord_id if actor else None,
        actor_display_name=actor.display_name if actor else None,
        by_commissioner=bool(is_commissioner),
    )
    db.add(row)
    return row


# ---------------------------------------------------------------------------
# The commissioner's feed
# ---------------------------------------------------------------------------

def list_changes(db, league, include_done=False, team_id=None, limit=200):
    q = db.query(MynbaGameplanChange).filter(MynbaGameplanChange.league_id == league.id)
    if not include_done:
        q = q.filter(MynbaGameplanChange.done_at.is_(None))
    if team_id:
        q = q.filter(MynbaGameplanChange.team_id == team_id)
    return q.order_by(MynbaGameplanChange.team_name, MynbaGameplanChange.created_at).limit(limit).all()


def mark_changes(db, league, change_ids, done, actor_discord_id=None):
    """Mark feed rows done (changed in 2K) or reopen them. Returns the rows touched."""
    if not change_ids:
        return []
    rows = db.query(MynbaGameplanChange).filter(
        MynbaGameplanChange.league_id == league.id,
        MynbaGameplanChange.id.in_(list(change_ids)),
    ).all()
    now = datetime.utcnow()
    for row in rows:
        row.done_at = now if done else None
        row.done_by_discord_id = str(actor_discord_id) if done and actor_discord_id else None
    db.flush()
    return rows


def change_json(row):
    return {
        "id": row.id,
        "team_id": row.team_id,
        "team": row.team_name,
        "field_key": row.field_key,
        "field": row.field_label,
        "is_rotation": row.field_key.startswith("rotation:"),
        "old_value": row.old_value,
        "new_value": row.new_value,
        "by": row.actor_display_name,
        "by_commissioner": row.by_commissioner,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "done": row.done_at is not None,
        "done_at": _iso(row.done_at),
    }
