---
name: gitnexus-area-frontend
description: "Skill for the Frontend area of knowledge-agent. 88 symbols across 1 files."
---

# Frontend

88 symbols | 1 files | Cohesion: 65%

## When to Use

- Working with code in `frontend/`
- Understanding how $$, adminAddMember, adminAssignRoles work
- Modifying frontend-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `frontend/app.js` | $$, adminAddMember, adminAssignRoles, adminCreateRole, adminCreateTeam (+83) |

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `$$` | Function | `frontend/app.js` | 17 |
| `adminAddMember` | Function | `frontend/app.js` | 107 |
| `adminAssignRoles` | Function | `frontend/app.js` | 96 |
| `adminCreateRole` | Function | `frontend/app.js` | 99 |
| `adminCreateTeam` | Function | `frontend/app.js` | 103 |
| `adminCreateUser` | Function | `frontend/app.js` | 94 |
| `adminDeleteRole` | Function | `frontend/app.js` | 101 |
| `adminDeleteTeam` | Function | `frontend/app.js` | 105 |
| `adminDeleteUser` | Function | `frontend/app.js` | 97 |
| `adminEditRole` | Function | `frontend/app.js` | 100 |
| `adminEditTeam` | Function | `frontend/app.js` | 104 |
| `adminEditUser` | Function | `frontend/app.js` | 95 |
| `adminPermissionCodes` | Function | `frontend/app.js` | 80 |
| `adminRemoveMember` | Function | `frontend/app.js` | 108 |
| `adminReviewAction` | Function | `frontend/app.js` | 98 |
| `adminSavePermissions` | Function | `frontend/app.js` | 102 |
| `adminSetTab` | Function | `frontend/app.js` | 83 |
| `adminShowMembers` | Function | `frontend/app.js` | 106 |
| `bindAdminEvents` | Function | `frontend/app.js` | 111 |
| `deleteDocument` | Function | `frontend/app.js` | 74 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `BindAdminEvents → $` | cross_community | 6 |
| `BindAdminEvents → ApiUrl` | cross_community | 5 |
| `BindAdminEvents → AuthHeaders` | cross_community | 5 |
| `SaveProfile → $` | cross_community | 5 |
| `StreamAnswer → $` | cross_community | 5 |
| `SubmitAuth → $` | cross_community | 5 |
| `BindAdminEvents → Request` | cross_community | 4 |
| `SaveProfile → Initials` | cross_community | 4 |
| `StreamAnswer → ChatStorageKey` | cross_community | 4 |
| `StreamAnswer → EscapeHtml` | cross_community | 4 |

## How to Explore

1. `context({name: "$$"})` — see callers and callees
2. `query({search_query: "frontend"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
