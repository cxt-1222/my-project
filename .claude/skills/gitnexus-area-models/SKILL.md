---
name: gitnexus-area-models
description: "Skill for the Models area of knowledge-agent. 13 symbols across 8 files."
---

# Models

13 symbols | 8 files | Cohesion: 100%

## When to Use

- Working with code in `models/`
- Understanding how Base, AiMessageModel, AiSessionModel work
- Modifying models-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `models/user.py` | RoleModel, UserModel, UserRoleModel |
| `models/chat.py` | AiMessageModel, AiSessionModel |
| `models/permission.py` | PermissionModel, RolePermissionModel |
| `models/team.py` | TeamMemberModel, TeamModel |
| `core/database.py` | Base |
| `models/document.py` | KhDocument |
| `models/graph_document.py` | GraphDocModel |
| `models/review.py` | ReviewTaskModel |

## Entry Points

Start here when exploring this area:

- **`Base`** (Class) — `core/database.py:18`
- **`AiMessageModel`** (Class) — `models/chat.py:20`
- **`AiSessionModel`** (Class) — `models/chat.py:8`
- **`KhDocument`** (Class) — `models/document.py:9`
- **`GraphDocModel`** (Class) — `models/graph_document.py:6`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `Base` | Class | `core/database.py` | 18 |
| `AiMessageModel` | Class | `models/chat.py` | 20 |
| `AiSessionModel` | Class | `models/chat.py` | 8 |
| `KhDocument` | Class | `models/document.py` | 9 |
| `GraphDocModel` | Class | `models/graph_document.py` | 6 |
| `PermissionModel` | Class | `models/permission.py` | 8 |
| `RolePermissionModel` | Class | `models/permission.py` | 20 |
| `ReviewTaskModel` | Class | `models/review.py` | 8 |
| `TeamMemberModel` | Class | `models/team.py` | 22 |
| `TeamModel` | Class | `models/team.py` | 8 |
| `RoleModel` | Class | `models/user.py` | 20 |
| `UserModel` | Class | `models/user.py` | 8 |
| `UserRoleModel` | Class | `models/user.py` | 32 |

## How to Explore

1. `context({name: "Base"})` — see callers and callees
2. `query({search_query: "models"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
