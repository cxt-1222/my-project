---
name: gitnexus-area-services
description: "Skill for the Services area of knowledge-agent. 10 symbols across 3 files."
---

# Services

10 symbols | 3 files | Cohesion: 91%

## When to Use

- Working with code in `services/`
- Understanding how check_neo4j_table, insert_neo4j_table, create_graph_doc work
- Modifying services-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `services/graph_service.py` | _get_doc_or_none, create_graph_doc, delete_graph_doc, get_graph_doc, graph_doc_exists |
| `services/llm_service.py` | get_entity_relationship, neo4j_prompt, separation_entity_relationship |
| `api/neo4j.py` | check_neo4j_table, insert_neo4j_table |

## Entry Points

Start here when exploring this area:

- **`check_neo4j_table`** (Function) — `api/neo4j.py:26`
- **`insert_neo4j_table`** (Function) — `api/neo4j.py:31`
- **`create_graph_doc`** (Function) — `services/graph_service.py:21`
- **`delete_graph_doc`** (Function) — `services/graph_service.py:65`
- **`get_graph_doc`** (Function) — `services/graph_service.py:57`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `check_neo4j_table` | Function | `api/neo4j.py` | 26 |
| `insert_neo4j_table` | Function | `api/neo4j.py` | 31 |
| `create_graph_doc` | Function | `services/graph_service.py` | 21 |
| `delete_graph_doc` | Function | `services/graph_service.py` | 65 |
| `get_graph_doc` | Function | `services/graph_service.py` | 57 |
| `graph_doc_exists` | Function | `services/graph_service.py` | 16 |
| `get_entity_relationship` | Function | `services/llm_service.py` | 89 |
| `neo4j_prompt` | Function | `services/llm_service.py` | 17 |
| `separation_entity_relationship` | Function | `services/llm_service.py` | 75 |
| `_get_doc_or_none` | Function | `services/graph_service.py` | 11 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Entity_relationship → Neo4j_prompt` | cross_community | 4 |

## How to Explore

1. `context({name: "check_neo4j_table"})` — see callers and callees
2. `query({search_query: "services"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
