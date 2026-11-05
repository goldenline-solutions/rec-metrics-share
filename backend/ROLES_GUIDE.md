# Roles and Permissions Guide

This guide explains how to assign and use roles and permissions in the 2K Stats Desk application.

## Overview

Roles and permissions are stored in the `users` table as JSON strings:
- `roles` - JSON array of role names (e.g., `["admin", "moderator"]`)
- `permissions` - JSON array of permission names (e.g., `["upload", "delete"]`)

## Assigning Roles

### Using the Script (Recommended)

Use the `assign_roles.py` script to assign roles and permissions:

```bash
cd backend

# Assign roles to a user by Discord ID
python scripts/assign_roles.py 123456789012345678 admin

# Assign roles to a user by email
python scripts/assign_roles.py user@example.com admin moderator

# Assign permissions
python scripts/assign_roles.py 123456789012345678 --permissions upload delete

# View current roles and permissions
python scripts/assign_roles.py 123456789012345678 --list

# Clear roles
python scripts/assign_roles.py 123456789012345678 --clear-roles
```

### Using SQLite Directly

You can also update roles directly in the database:

```bash
cd backend
sqlite3 app.db
```

```sql
-- View all users and their roles
SELECT discord_username, email, roles, permissions FROM users;

-- Assign roles to a user (replace USER_ID and roles as needed)
UPDATE users 
SET roles = '["admin", "moderator"]' 
WHERE discord_id = '123456789012345678';

-- Assign permissions
UPDATE users 
SET permissions = '["upload", "delete", "edit"]' 
WHERE discord_id = '123456789012345678';

-- Clear roles
UPDATE users SET roles = NULL WHERE discord_id = '123456789012345678';
```

**Important:** The roles and permissions must be valid JSON arrays. Examples:
- `'["admin"]'` - Single role
- `'["admin", "moderator"]'` - Multiple roles
- `NULL` - No roles/permissions

## Common Roles

- `admin` - Full administrative access
- `moderator` - Can moderate content
- `user` - Standard user (default, can be omitted)

## Common Permissions

- `upload` - Can upload screenshots
- `delete` - Can delete games/data
- `edit` - Can edit games/data
- `view_analytics` - Can view analytics page

## Using Roles in Code

### Backend (Python)

```python
from models import User
import json

# Get user roles
user = db.query(User).filter_by(id=user_id).first()
roles = json.loads(user.roles) if user.roles else []

# Check if user has role
if 'admin' in roles:
    # Allow admin action
    pass

# Check if user has permission
permissions = json.loads(user.permissions) if user.permissions else []
if 'delete' in permissions:
    # Allow delete action
    pass
```

### Frontend (React)

```javascript
import { useAuth } from '../contexts/AuthContext'
import { hasRole, hasPermission } from '../utils/api'

function MyComponent() {
  const { user } = useAuth()
  
  // Check role
  if (hasRole(user, 'admin')) {
    // Show admin features
  }
  
  // Check permission
  if (hasPermission(user, 'upload')) {
    // Show upload button
  }
}
```

## Example: Protecting Routes

You can use roles/permissions to protect routes or features:

```javascript
// In a component
const { user } = useAuth()

if (!hasRole(user, 'admin')) {
  return <Navigate to="/" replace />
}

// Or conditionally render
{hasPermission(user, 'view_analytics') && (
  <NavLink to="/analytics">Analytics</NavLink>
)}
```

## Database Schema

The `users` table now includes:
- `roles` (TEXT, nullable) - JSON array of role names
- `permissions` (TEXT, nullable) - JSON array of permission names

These fields are automatically created when you run the app (via SQLAlchemy's `init_db()`).

## Notes

- Roles and permissions are stored as JSON strings in the database
- Empty arrays `[]` and `NULL` are treated the same (no roles/permissions)
- The `/api/me` endpoint automatically parses and returns roles/permissions as arrays
- Invalid JSON is handled gracefully (returns empty array)

