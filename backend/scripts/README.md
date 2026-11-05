# Database Utility Scripts

## assign_roles.py

Script to assign roles and permissions to users in the database.

### Usage

```bash
# Assign roles to a user (by Discord ID or email)
python scripts/assign_roles.py <discord_id_or_email> <role1> [role2] [role3] ...

# Assign permissions to a user
python scripts/assign_roles.py <discord_id_or_email> --permissions <perm1> [perm2] ...

# List current roles and permissions for a user
python scripts/assign_roles.py <discord_id_or_email> --list

# Clear all roles for a user
python scripts/assign_roles.py <discord_id_or_email> --clear-roles

# Clear all permissions for a user
python scripts/assign_roles.py <discord_id_or_email> --clear-permissions
```

### Examples

```bash
# Assign admin role to a user by Discord ID
python scripts/assign_roles.py 123456789012345678 admin

# Assign multiple roles
python scripts/assign_roles.py user@example.com admin moderator

# Assign permissions
python scripts/assign_roles.py 123456789012345678 --permissions upload delete edit

# View current roles and permissions
python scripts/assign_roles.py 123456789012345678 --list

# Clear roles
python scripts/assign_roles.py 123456789012345678 --clear-roles
```

### Common Roles

- `admin` - Full administrative access
- `moderator` - Can moderate content
- `user` - Standard user (default)

### Common Permissions

- `upload` - Can upload screenshots
- `delete` - Can delete games/data
- `edit` - Can edit games/data
- `view_analytics` - Can view analytics page

## generate_matchups.py

Script to auto-generate matchups for all games that don't have exactly 10 matchups.

### Usage

```bash
cd backend
python scripts/generate_matchups.py
```

### What It Does

1. Finds all games in the database
2. Checks if each game has exactly 10 matchups (5 positions × 2 directions)
3. For games without 10 matchups:
   - Deletes existing matchups
   - Generates 10 new matchups based on player positions
   - Creates matchups for each position (PG, SG, SF, PF, C):
     - HOME defender vs AWAY offender
     - AWAY defender vs HOME offender
4. Saves all generated matchups to the database

### Matchup Structure

Each game should have exactly 10 matchups:
- **5 positions** (PG, SG, SF, PF, C)
- **2 directions** per position:
  - HOME defender vs AWAY offender
  - AWAY defender vs HOME offender

### Example Output

```
============================================================
Matchup Generation Script
============================================================

Found 25 games in database.
  Game abc12345...: Already has 10 matchups ✓
  Game def67890...: Has 5 matchups (expected 10)
    ✓ Generated 10 matchups
  Game ghi11111...: Has 0 matchups (expected 10)
    ✓ Generated 10 matchups

============================================================
Summary:
  Games processed: 25
  Games updated: 2
  Matchups created: 20
  Matchups deleted: 5
============================================================
✓ Matchup generation completed!
```

### Notes

- The script will ask for confirmation before making changes
- It only updates games that don't have exactly 10 matchups
- If a game is missing players at certain positions, it will generate fewer matchups (with a warning)
- All changes are committed per game (transactional)

## find_missing_stats.py

Script to find games where players have GamePlayer entries but are missing PlayerGameStats records.

### Usage

```bash
cd backend
python scripts/find_missing_stats.py
```

### What It Does

1. Scans all games in the database
2. For each game, checks if all GamePlayer entries have corresponding PlayerGameStats
3. Reports which games and players are missing stats
4. Provides a summary of the total number of affected games and players

### Example Output

```
Checking 150 games for missing player stats...

⚠️  Found 4 games with missing player stats:

================================================================================

Game ID: abc12345-6789-0123-4567-890123456789
Date: 2025-12-28T15:30:00
Match: Team A @ Team B (85-92)
Missing Stats: 1 player(s)
  - HintofLime (PG, HOME)
--------------------------------------------------------------------------------

Game ID: def67890-1234-5678-9012-345678901234
Date: 2025-12-27T20:15:00
Match: Team C @ Team D (78-88)
Missing Stats: 2 player(s)
  - PlayerOne (SG, AWAY)
  - PlayerTwo (PF, HOME)
--------------------------------------------------------------------------------

📊 Summary:
   Total games with issues: 4
   Total players missing stats: 5

💡 These games will now show warnings when viewed.
   You can fix them by editing the games and adding the missing stats.
```

### Notes

- This script is read-only and doesn't modify any data
- Games with missing stats will automatically show warnings when viewed via the API
- Missing stats can be fixed by editing the game through the admin interface
- The validation check is also automatically run when viewing games via `/api/games/<game_id>`

