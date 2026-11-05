"""
Who can get into the league portal.

Route-level checks through Flask's test client with real session cookies, because
the interesting logic (site admin, GM, commissioner, outsider) lives in the
request layer, not the service layer. Creates a throwaway league and users, then
deletes them.

    python test_mynba_access.py
"""
import json
import sys

from app import app
from db import SessionLocal
from models import User
from auth_utils import create_session_token
import mynba_service as svc
from mynba_models import (
    MynbaLeague, MynbaCommissioner, MynbaTeam, MynbaPlayer,
    MynbaTrade, MynbaTradeAsset, MynbaTradeVote, MynbaTransaction,
)

GUILD = "test-guild-mynba-access"
USERS = {
    "admin": ("acc-admin-1", ["admin"]),
    "commish": ("acc-commish-1", []),
    "gm": ("acc-gm-1", []),
    "outsider": ("acc-outsider-1", []),
}

passes, failures = [], []


def check(label, condition, detail=""):
    if condition:
        passes.append(label)
        print(f"  PASS  {label}")
    else:
        failures.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))


def cleanup(db):
    league = svc.get_league(db, GUILD)
    if league:
        ids = [t.id for t in db.query(MynbaTrade).filter(MynbaTrade.league_id == league.id).all()]
        if ids:
            db.query(MynbaTradeVote).filter(MynbaTradeVote.trade_id.in_(ids)).delete(synchronize_session=False)
            db.query(MynbaTradeAsset).filter(MynbaTradeAsset.trade_id.in_(ids)).delete(synchronize_session=False)
        for model in (MynbaTransaction, MynbaTrade, MynbaPlayer, MynbaCommissioner, MynbaTeam):
            db.query(model).filter(model.league_id == league.id).delete(synchronize_session=False)
        db.query(MynbaLeague).filter(MynbaLeague.id == league.id).delete(synchronize_session=False)
    for discord_id, _ in USERS.values():
        db.query(User).filter(User.discord_id == discord_id).delete(synchronize_session=False)
    db.commit()


def run():
    db = SessionLocal()
    tokens = {}
    try:
        cleanup(db)

        # Only one league may exist for the no-guild_id fallback to resolve, so
        # these calls always name the guild explicitly.
        league = svc.create_league(db, GUILD, name="Access Test League")
        svc.import_roster_csv(db, league, "Name,Team\nTest Player,Bulls\n")

        for key, (discord_id, roles) in USERS.items():
            user = User(discord_id=discord_id, discord_username=key, display_name=key,
                        roles=json.dumps(roles) if roles else None)
            db.add(user)
            db.flush()
            tokens[key] = create_session_token(user.id)

        bulls = svc.resolve_team(db, league.id, "Bulls")
        bulls.gm_discord_id, bulls.is_cpu, bulls.gm_display_name = USERS["gm"][0], False, "gm"
        db.add(MynbaCommissioner(league_id=league.id, discord_id=USERS["commish"][0]))
        db.commit()

        client = app.test_client()

        def me(key):
            client.set_cookie("access_token", tokens[key], domain="localhost")
            res = client.get(f"/api/mynba/me?guild_id={GUILD}")
            return res.status_code, res.get_json()

        print("\nSite admin — no GM row, no commissioner row")
        status, body = me("admin")
        check("admin reaches the portal", body["is_member"] is True, str(body))
        check("admin gets commissioner powers", body["is_commissioner"] is True, str(body))
        check("admin has no team of their own", body["team"] is None, str(body.get("team")))
        check("admin sees league settings", body["league"].get("roster_size") == 8, str(body["league"]))

        print("\nCommissioner")
        status, body = me("commish")
        check("commissioner reaches the portal", body["is_member"] is True)
        check("commissioner has commissioner powers", body["is_commissioner"] is True)

        print("\nGM")
        status, body = me("gm")
        check("GM reaches the portal", body["is_member"] is True)
        check("GM is not a commissioner", body["is_commissioner"] is False)
        check("GM sees their team", body["team"] and body["team"]["name"] == "Bulls", str(body.get("team")))

        print("\nSigned-in outsider")
        status, body = me("outsider")
        check("outsider is not a member", body["is_member"] is False, str(body))
        check("outsider is told the league name only", "roster_size" not in body["league"], str(body["league"]))

        print("\nOutsider is blocked from the data, not just the UI")
        client.set_cookie("access_token", tokens["outsider"], domain="localhost")
        for path in (f"/api/mynba/teams?guild_id={GUILD}",
                     f"/api/mynba/free-agents?guild_id={GUILD}",
                     f"/api/mynba/trades?guild_id={GUILD}",
                     f"/api/mynba/transactions?guild_id={GUILD}"):
            res = client.get(path)
            check(f"403 on {path.split('?')[0]}", res.status_code == 403, f"got {res.status_code}")

        print("\nSigned-out visitor")
        client.delete_cookie("access_token", domain="localhost")
        res = client.get(f"/api/mynba/teams?guild_id={GUILD}")
        check("anonymous is refused", res.status_code == 403, f"got {res.status_code}")

        print("\nAdmin can use commissioner-only endpoints")
        client.set_cookie("access_token", tokens["admin"], domain="localhost")
        res = client.patch(f"/api/mynba/league?guild_id={GUILD}",
                           json={"guild_id": GUILD, "trades_locked": True})
        check("admin can lock trading", res.status_code == 200, f"{res.status_code} {res.get_data(as_text=True)[:120]}")

        client.set_cookie("access_token", tokens["gm"], domain="localhost")
        res = client.patch(f"/api/mynba/league?guild_id={GUILD}",
                           json={"guild_id": GUILD, "trades_locked": False})
        check("a plain GM cannot", res.status_code == 403, f"got {res.status_code}")

    finally:
        cleanup(db)
        db.close()

    print(f"\n{len(passes)} passed, {len(failures)} failed")
    for f in failures:
        print(f"  FAILED: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
