"""
Scan all players for fuzzy-name duplicates caused by OCR misreads and merge them.

Detection uses rapidfuzz token-level similarity.  Two gamertags are considered
candidates if their case-insensitive ratio is >= THRESHOLD (default 88).
Transitive matches are grouped together (A~B, B~C → one cluster of A,B,C).

The "winner" in each cluster is whichever gamertag has appeared in the most
games.  All FK references for every other player in the cluster are re-pointed
to the winner, then the loser rows are deleted.

FK tables updated:
  - game_players.player_id
  - player_game_stats.player_id
  - matchups.defender_player_id / offender_player_id
  - player_game_admin_metrics.player_id

Also purges stale PlayerAnalysisCache rows for the losers (string username).

Usage:
  python fuzzy_merge_players.py                        # dry-run, threshold=88
  python fuzzy_merge_players.py --threshold 92         # stricter
  python fuzzy_merge_players.py --player HintofLime    # show only clusters containing this player
  python fuzzy_merge_players.py --execute              # apply merges
  python fuzzy_merge_players.py --execute --threshold 92
"""

import argparse
from collections import defaultdict
from rapidfuzz import fuzz

from db import SessionLocal, init_db
from models import (
    Player, GamePlayer, PlayerGameStats, Matchup,
    PlayerAnalysisCache, PlayerGameAdminMetrics,
)


# ---------------------------------------------------------------------------
# Union-Find  (groups transitive fuzzy matches into one cluster)
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self, keys):
        self.parent = {k: k for k in keys}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def groups(self):
        buckets = defaultdict(list)
        for k in self.parent:
            buckets[self.find(k)].append(k)
        return [v for v in buckets.values() if len(v) > 1]


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

def game_count(db, player_id: str) -> int:
    return db.query(GamePlayer).filter(GamePlayer.player_id == player_id).count()


def merge_player_refs(db, from_id: str, to_id: str):
    """Re-point every FK that references from_id to to_id."""
    db.query(GamePlayer).filter(GamePlayer.player_id == from_id).update(
        {"player_id": to_id}, synchronize_session=False
    )
    db.query(PlayerGameStats).filter(PlayerGameStats.player_id == from_id).update(
        {"player_id": to_id}, synchronize_session=False
    )
    db.query(Matchup).filter(Matchup.defender_player_id == from_id).update(
        {"defender_player_id": to_id}, synchronize_session=False
    )
    db.query(Matchup).filter(Matchup.offender_player_id == from_id).update(
        {"offender_player_id": to_id}, synchronize_session=False
    )
    db.query(PlayerGameAdminMetrics).filter(PlayerGameAdminMetrics.player_id == from_id).update(
        {"player_id": to_id}, synchronize_session=False
    )


def purge_cache(db, gamertag: str):
    db.query(PlayerAnalysisCache).filter(
        PlayerAnalysisCache.username == gamertag
    ).delete(synchronize_session=False)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def find_fuzzy_clusters(players, threshold: int, filter_player: str | None):
    """
    Return a list of clusters (each a list of Player objects) that contain
    more than one entry with pairwise similarity >= threshold.

    If filter_player is set, only return clusters that contain that gamertag
    (case-insensitive).
    """
    tags = [p.gamertag for p in players]
    uf = UnionFind(tags)

    n = len(tags)
    for i in range(n):
        for j in range(i + 1, n):
            score = fuzz.ratio(tags[i].lower(), tags[j].lower())
            if score >= threshold:
                uf.union(tags[i], tags[j])

    raw_groups = uf.groups()

    # Build a map from gamertag → Player for quick lookup
    by_tag = {p.gamertag: p for p in players}

    clusters = []
    for group_tags in raw_groups:
        cluster = [by_tag[t] for t in group_tags if t in by_tag]
        if len(cluster) < 2:
            continue
        if filter_player:
            has_target = any(
                filter_player.lower() == p.gamertag.lower() for p in cluster
            )
            if not has_target:
                continue
        clusters.append(cluster)

    return clusters


def run(dry_run: bool, threshold: int, filter_player: str | None):
    db = SessionLocal()
    try:
        all_players = db.query(Player).all()
        print(f"Loaded {len(all_players)} players.  Similarity threshold: {threshold}%\n")

        clusters = find_fuzzy_clusters(all_players, threshold, filter_player)

        if not clusters:
            print("No fuzzy duplicates found.")
            return

        # Sort: largest clusters first
        clusters.sort(key=lambda c: -len(c))

        total_merges = sum(len(c) - 1 for c in clusters)
        print(f"Found {len(clusters)} cluster(s) with {total_merges} player(s) to merge.\n")
        print("=" * 70)

        for cluster in clusters:
            # Count games per player to determine winner
            counts = {p.id: game_count(db, p.id) for p in cluster}
            # Winner = most games; tie-break = alphabetical (deterministic)
            winner = max(cluster, key=lambda p: (counts[p.id], p.gamertag.lower()))
            losers = [p for p in cluster if p.id != winner.id]

            print(f"CLUSTER  (winner: {winner.gamertag!r}  —  {counts[winner.id]} games)")
            for p in losers:
                score = fuzz.ratio(winner.gamertag.lower(), p.gamertag.lower())
                action = "would merge" if dry_run else "merging"
                print(
                    f"  {action}  {p.gamertag!r}  →  {winner.gamertag!r}"
                    f"   [similarity {score}%,  {counts[p.id]} games]"
                )

            if not dry_run:
                for loser in losers:
                    merge_player_refs(db, loser.id, winner.id)
                    purge_cache(db, loser.gamertag)
                    db.flush()
                    db.delete(loser)
                db.flush()

            print()

        print("=" * 70)
        if dry_run:
            print(f"\nDRY RUN — {total_merges} merge(s) pending.  Re-run with --execute to apply.")
        else:
            db.commit()
            print(f"\nDone.  Merged {total_merges} player(s) into their winners.")

    except Exception as exc:
        db.rollback()
        print(f"\nERROR: {exc}")
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Find and merge fuzzy-duplicate player names caused by OCR misreads."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply merges (default is dry-run).",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=88,
        metavar="0-100",
        help="Minimum similarity score to consider two names duplicates (default: 88).",
    )
    parser.add_argument(
        "--player",
        metavar="GAMERTAG",
        default=None,
        help="Only show clusters that contain this gamertag (case-insensitive).",
    )
    args = parser.parse_args()

    if not 50 <= args.threshold <= 100:
        parser.error("--threshold must be between 50 and 100")

    init_db()
    run(dry_run=not args.execute, threshold=args.threshold, filter_player=args.player)


if __name__ == "__main__":
    main()
