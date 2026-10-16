---
name: gitnexus-area-schemas
description: "Skill for the Schemas area of knowledge-agent. 6 symbols across 2 files."
---

# Schemas

6 symbols | 2 files | Cohesion: 100%

## When to Use

- Working with code in `schemas/`
- Understanding how GraphDocCreate, GraphDocOut, RoleRespDTO work
- Modifying schemas-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `schemas/user.py` | RoleRespDTO, RoleWithUsersRespDTO, UserRespDTO, UserWithRolesRespDTO |
| `schemas/graph.py` | GraphDocCreate, GraphDocOut |

## Entry Points

Start here when exploring this area:

- **`GraphDocCreate`** (Class) — `schemas/graph.py:12`
- **`GraphDocOut`** (Class) — `schemas/graph.py:20`
- **`RoleRespDTO`** (Class) — `schemas/user.py:77`
- **`RoleWithUsersRespDTO`** (Class) — `schemas/user.py:87`
- **`UserRespDTO`** (Class) — `schemas/user.py:38`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `GraphDocCreate` | Class | `schemas/graph.py` | 12 |
| `GraphDocOut` | Class | `schemas/graph.py` | 20 |
| `RoleRespDTO` | Class | `schemas/user.py` | 77 |
| `RoleWithUsersRespDTO` | Class | `schemas/user.py` | 87 |
| `UserRespDTO` | Class | `schemas/user.py` | 38 |
| `UserWithRolesRespDTO` | Class | `schemas/user.py` | 47 |

## How to Explore

1. `context({name: "GraphDocCreate"})` — see callers and callees
2. `query({search_query: "schemas"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
