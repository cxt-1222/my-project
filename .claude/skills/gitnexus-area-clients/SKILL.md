---
name: gitnexus-area-clients
description: "Skill for the Clients area of knowledge-agent. 52 symbols across 17 files."
---

# Clients

52 symbols | 17 files | Cohesion: 74%

## When to Use

- Working with code in `clients/`
- Understanding how async_es, delete_all_data, es_check work
- Modifying clients-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `clients/es_client.py` | check_data, close_es, delete_all_data, init_es, _visible_filter (+7) |
| `clients/tencent_speech.py` | _asr_build_ws_url, _extract_asr_text, _is_sentence_final, run_asr_bridge, client_to_upstream (+7) |
| `api/es.py` | async_es, delete_all_data, es_check, search_all_data, search_data (+2) |
| `clients/milvus_client.py` | embedding_text, search_milvus_data, _flush_vector_batch, _vector_writer_loop, start_vector_writer (+1) |
| `clients/neo4j_client.py` | close_neo4j_driver, init_neo4j_driver |
| `clients/web_search.py` | _search, web_search |
| `clients/rabbitmq/mq.py` | close_mq |
| `clients/rustfs.py` | init_rustfs_bucket |
| `main.py` | lifespan |
| `scripts/check_infra_state.py` | main |

## Entry Points

Start here when exploring this area:

- **`async_es`** (Function) — `api/es.py:20`
- **`delete_all_data`** (Function) — `api/es.py:91`
- **`es_check`** (Function) — `api/es.py:58`
- **`check_data`** (Function) — `clients/es_client.py:42`
- **`close_es`** (Function) — `clients/es_client.py:25`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `async_es` | Function | `api/es.py` | 20 |
| `delete_all_data` | Function | `api/es.py` | 91 |
| `es_check` | Function | `api/es.py` | 58 |
| `check_data` | Function | `clients/es_client.py` | 42 |
| `close_es` | Function | `clients/es_client.py` | 25 |
| `delete_all_data` | Function | `clients/es_client.py` | 180 |
| `init_es` | Function | `clients/es_client.py` | 7 |
| `close_neo4j_driver` | Function | `clients/neo4j_client.py` | 19 |
| `init_neo4j_driver` | Function | `clients/neo4j_client.py` | 7 |
| `close_mq` | Function | `clients/rabbitmq/mq.py` | 27 |
| `init_rustfs_bucket` | Function | `clients/rustfs.py` | 21 |
| `lifespan` | Function | `main.py` | 33 |
| `main` | Function | `scripts/check_infra_state.py` | 18 |
| `init_mongodb` | Function | `services/content_service.py` | 13 |
| `search_all_data` | Function | `api/es.py` | 82 |
| `search_data` | Function | `api/es.py` | 64 |
| `search_hightlight_data` | Function | `api/es.py` | 72 |
| `search_all_data` | Function | `clients/es_client.py` | 161 |
| `search_data` | Function | `clients/es_client.py` | 72 |
| `search_hightlight_data` | Function | `clients/es_client.py` | 103 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Ai_invoke → _hit_field` | cross_community | 5 |
| `Ai_invoke → Init_es` | cross_community | 5 |
| `Ai_invoke → _visible_filter` | cross_community | 5 |
| `Ai_invoke → Embedding_text` | cross_community | 5 |
| `Lifespan → Queue_arguments` | cross_community | 5 |
| `Tts_http → _tts_generate_signature` | intra_community | 4 |
| `Ws_stt → _extract_asr_text` | cross_community | 4 |
| `Ws_stt → _is_sentence_final` | cross_community | 4 |
| `Ws_stt → Full_text` | cross_community | 4 |
| `Lifespan → _flush_vector_batch` | cross_community | 4 |

## How to Explore

1. `context({name: "async_es"})` — see callers and callees
2. `query({search_query: "clients"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
