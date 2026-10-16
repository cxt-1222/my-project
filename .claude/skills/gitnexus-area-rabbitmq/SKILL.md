---
name: gitnexus-area-rabbitmq
description: "Skill for the Rabbitmq area of knowledge-agent. 13 symbols across 6 files."
---

# Rabbitmq

13 symbols | 6 files | Cohesion: 87%

## When to Use

- Working with code in `clients/`
- Understanding how queue_arguments, consume_index, consume_kg work
- Modifying rabbitmq-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `clients/rabbitmq/consumer.py` | consume_index, consume_kg, consume_rag, _write_flow, handle_kg_msg (+1) |
| `clients/rabbitmq/connection.py` | queue_arguments, connect, declare_work_queue |
| `clients/rabbitmq/mq.py` | init_mq |
| `clients/milvus_client.py` | milvus_insert |
| `services/document_service.py` | update_flow_status |
| `utils/split_file.py` | split_doc |

## Entry Points

Start here when exploring this area:

- **`queue_arguments`** (Function) — `clients/rabbitmq/connection.py:7`
- **`consume_index`** (Function) — `clients/rabbitmq/consumer.py:70`
- **`consume_kg`** (Function) — `clients/rabbitmq/consumer.py:89`
- **`consume_rag`** (Function) — `clients/rabbitmq/consumer.py:80`
- **`init_mq`** (Function) — `clients/rabbitmq/mq.py:16`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `queue_arguments` | Function | `clients/rabbitmq/connection.py` | 7 |
| `consume_index` | Function | `clients/rabbitmq/consumer.py` | 70 |
| `consume_kg` | Function | `clients/rabbitmq/consumer.py` | 89 |
| `consume_rag` | Function | `clients/rabbitmq/consumer.py` | 80 |
| `init_mq` | Function | `clients/rabbitmq/mq.py` | 16 |
| `milvus_insert` | Function | `clients/milvus_client.py` | 95 |
| `handle_kg_msg` | Function | `clients/rabbitmq/consumer.py` | 55 |
| `handle_rag_msg` | Function | `clients/rabbitmq/consumer.py` | 40 |
| `update_flow_status` | Function | `services/document_service.py` | 40 |
| `split_doc` | Function | `utils/split_file.py` | 6 |
| `connect` | Method | `clients/rabbitmq/connection.py` | 24 |
| `declare_work_queue` | Method | `clients/rabbitmq/connection.py` | 45 |
| `_write_flow` | Function | `clients/rabbitmq/consumer.py` | 15 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Lifespan → Queue_arguments` | cross_community | 5 |
| `Handle_rag_msg → Update_flow_status` | intra_community | 3 |
| `Handle_rag_msg → Milvus_insert` | intra_community | 3 |

## How to Explore

1. `context({name: "queue_arguments"})` — see callers and callees
2. `query({search_query: "rabbitmq"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
