---
name: gitnexus-area-parsers
description: "Skill for the Parsers area of knowledge-agent. 6 symbols across 5 files."
---

# Parsers

6 symbols | 5 files | Cohesion: 77%

## When to Use

- Working with code in `utils/`
- Understanding how upload_file, extract_docx_text_and_images, extract_pdf_text_and_images work
- Modifying parsers-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `utils/parsers/pptx_parse.py` | extract_pptx_text_and_images, iterate_shape |
| `api/file.py` | upload_file |
| `utils/parsers/docx_parse.py` | extract_docx_text_and_images |
| `utils/parsers/pdf_parse.py` | extract_pdf_text_and_images |
| `utils/parsers/xlsx_parse.py` | extract_xlsx_text_and_images |

## Entry Points

Start here when exploring this area:

- **`upload_file`** (Function) — `api/file.py:56`
- **`extract_docx_text_and_images`** (Function) — `utils/parsers/docx_parse.py:10`
- **`extract_pdf_text_and_images`** (Function) — `utils/parsers/pdf_parse.py:3`
- **`extract_pptx_text_and_images`** (Function) — `utils/parsers/pptx_parse.py:7`
- **`iterate_shape`** (Function) — `utils/parsers/pptx_parse.py:17`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `upload_file` | Function | `api/file.py` | 56 |
| `extract_docx_text_and_images` | Function | `utils/parsers/docx_parse.py` | 10 |
| `extract_pdf_text_and_images` | Function | `utils/parsers/pdf_parse.py` | 3 |
| `extract_pptx_text_and_images` | Function | `utils/parsers/pptx_parse.py` | 7 |
| `iterate_shape` | Function | `utils/parsers/pptx_parse.py` | 17 |
| `extract_xlsx_text_and_images` | Function | `utils/parsers/xlsx_parse.py` | 6 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Upload_file → Iterate_shape` | intra_community | 3 |

## How to Explore

1. `context({name: "upload_file"})` — see callers and callees
2. `query({search_query: "parsers"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
