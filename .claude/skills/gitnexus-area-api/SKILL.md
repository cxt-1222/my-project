---
name: gitnexus-area-api
description: "Skill for the Api area of knowledge-agent. 113 symbols across 22 files."
---

# Api

113 symbols | 22 files | Cohesion: 88%

## When to Use

- Working with code in `api/`
- Understanding how ai_invoke, ai_invoke_stream, create_session_api work
- Modifying api-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `api/user.py` | assign_roles_api, del_user_api, query_users_api, user_roles_api, user_stats_api (+7) |
| `api/ai.py` | ai_invoke, ai_invoke_stream, _build_messages, _do_invoke, _sse (+5) |
| `api/team.py` | add_member_api, add_team_api, del_member_api, del_team_api, my_teams_api (+4) |
| `api/document.py` | _can_view, delete_kh_doc_api, get_all_docs, get_doc_api, update_kh_doc_api (+3) |
| `api/file.py` | download_file, delete_file, get_presigned_download_url, get_presigned_upload_url, multipart_complete (+3) |
| `api/role.py` | add_role_api, assign_permissions_api, bind_role_api, del_role_api, get_roles_api (+3) |
| `api/chat.py` | _get_owned_session, create_session_api, delete_session_api, get_session_api, list_sessions_api (+2) |
| `api/review.py` | pending_count_api, review_action_api, review_tasks_api, submit_review_api, task_of_doc_api (+1) |
| `services/document_service.py` | compute_parse_status, delete_kh_doc, get_doc, mark_parsing, update_kh_doc (+1) |
| `core/security.py` | can_review_doc, get_current_user, get_user_role_codes, is_admin_user, require_admin |

## Entry Points

Start here when exploring this area:

- **`ai_invoke`** (Function) — `api/ai.py:123`
- **`ai_invoke_stream`** (Function) — `api/ai.py:257`
- **`create_session_api`** (Function) — `api/chat.py:30`
- **`delete_session_api`** (Function) — `api/chat.py:70`
- **`get_session_api`** (Function) — `api/chat.py:51`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `ai_invoke` | Function | `api/ai.py` | 123 |
| `ai_invoke_stream` | Function | `api/ai.py` | 257 |
| `create_session_api` | Function | `api/chat.py` | 30 |
| `delete_session_api` | Function | `api/chat.py` | 70 |
| `get_session_api` | Function | `api/chat.py` | 51 |
| `list_sessions_api` | Function | `api/chat.py` | 43 |
| `update_session_api` | Function | `api/chat.py` | 57 |
| `delete_kh_doc_api` | Function | `api/document.py` | 113 |
| `get_all_docs` | Function | `api/document.py` | 64 |
| `get_doc_api` | Function | `api/document.py` | 35 |
| `update_kh_doc_api` | Function | `api/document.py` | 139 |
| `download_file` | Function | `api/file.py` | 110 |
| `delete_mongo_doc_api` | Function | `api/mongo.py` | 48 |
| `get_mongo_doc_api` | Function | `api/mongo.py` | 15 |
| `update_mongo_doc_api` | Function | `api/mongo.py` | 43 |
| `entity_relationship` | Function | `api/neo4j.py` | 35 |
| `graph_overview_api` | Function | `api/neo4j.py` | 48 |
| `permission_tree_api` | Function | `api/permission.py` | 57 |
| `mq_publish_es` | Function | `api/publish.py` | 42 |
| `publish_api` | Function | `api/publish.py` | 18 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Ai_invoke → _hit_field` | cross_community | 5 |
| `Ai_invoke → Init_es` | cross_community | 5 |
| `Ai_invoke → _visible_filter` | cross_community | 5 |
| `Ai_invoke → Embedding_text` | cross_community | 5 |
| `Entity_relationship → Neo4j_prompt` | cross_community | 4 |
| `Ws_stt → _extract_asr_text` | cross_community | 4 |
| `Ws_stt → _is_sentence_final` | cross_community | 4 |
| `Ws_stt → Full_text` | cross_community | 4 |
| `Ai_invoke_stream → _hit_field` | cross_community | 4 |
| `Ai_invoke_stream → Init_es` | cross_community | 4 |

## How to Explore

1. `context({name: "ai_invoke"})` — see callers and callees
2. `query({search_query: "api"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
