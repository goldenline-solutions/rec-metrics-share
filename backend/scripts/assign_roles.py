"""
Script to assign roles and permissions to users in the database.
Usage:
    python scripts/assign_roles.py <discord_id_or_email> <role1> [role2] [role3] ...
    python scripts/assign_roles.py <discord_id_or_email> --permissions <perm1> [perm2] ...
    python scripts/assign_roles.py <discord_id_or_email> --clear-roles
    python scripts/assign_roles.py <discord_id_or_email> --clear-permissions
    python scripts/assign_roles.py <discord_id_or_email> --list

Examples:
    python scripts/assign_roles.py 123456789012345678 admin
    python scripts/assign_roles.py user@example.com admin moderator
    python scripts/assign_roles.py 123456789012345678 --permissions upload delete
    python scripts/assign_roles.py 123456789012345678 --list
"""
import sys
import os
import json

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal
from models import User


def get_user_by_identifier(db, identifier):
    """Find user by discord_id or email."""
    # Try discord_id first
    user = db.query(User).filter_by(discord_id=identifier).first()
    if user:
        return user
    
    # Try email
    user = db.query(User).filter_by(email=identifier).first()
    if user:
        return user
    
    return None


def parse_roles_permissions(value):
    """Parse roles/permissions from JSON string or return empty list."""
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def format_roles_permissions(items):
    """Format roles/permissions list as JSON string."""
    return json.dumps(items) if items else None


def main():
    if len(sys.argv) < 3 and '--list' not in sys.argv and '--clear-roles' not in sys.argv and '--clear-permissions' not in sys.argv:
        print(__doc__)
        sys.exit(1)
    
    identifier = sys.argv[1]
    db = SessionLocal()
    
    try:
        user = get_user_by_identifier(db, identifier)
        if not user:
            print(f"Error: User not found with identifier: {identifier}")
            print("Try using Discord ID or email address.")
            sys.exit(1)
        
        # List current roles/permissions
        if '--list' in sys.argv:
            roles = parse_roles_permissions(user.roles)
            permissions = parse_roles_permissions(user.permissions)
            print(f"\nUser: {user.display_name or user.discord_username} ({user.email or 'no email'})")
            print(f"Discord ID: {user.discord_id}")
            print(f"Roles: {roles if roles else '[]'}")
            print(f"Permissions: {permissions if permissions else '[]'}")
            return
        
        # Clear roles
        if '--clear-roles' in sys.argv:
            user.roles = None
            db.commit()
            print(f"Cleared roles for user: {user.display_name or user.discord_username}")
            return
        
        # Clear permissions
        if '--clear-permissions' in sys.argv:
            user.permissions = None
            db.commit()
            print(f"Cleared permissions for user: {user.display_name or user.discord_username}")
            return
        
        # Handle permissions assignment
        if '--permissions' in sys.argv:
            perm_index = sys.argv.index('--permissions')
            if perm_index + 1 >= len(sys.argv):
                print("Error: --permissions requires at least one permission")
                sys.exit(1)
            
            permissions = sys.argv[perm_index + 1:]
            user.permissions = format_roles_permissions(permissions)
            db.commit()
            print(f"Assigned permissions to {user.display_name or user.discord_username}: {permissions}")
            return
        
        # Handle roles assignment (default)
        roles = sys.argv[2:]
        user.roles = format_roles_permissions(roles)
        db.commit()
        print(f"Assigned roles to {user.display_name or user.discord_username}: {roles}")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

