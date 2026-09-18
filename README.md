# IPMAT Mock System (IIMB pattern)

Canonical spec: 60 MCQs (30 QA + 15 LR + 15 VARC), 135 min (8100 s),
marking +3 correct / −1 wrong / 0 skipped. See `exam scheme/`.

Bank: 77 questions (47 QA incl. Arithmetic + DI backfill, 15 LR, 15 VARC).

## Layout
- `schemas/` — v2 question + paper JSON schemas
- `blueprints/` — full-mock-60q, sectional QA/LR/VARC, mixed practice
- `prompts/` — generator system + QA/LR/VARC/DI batch prompts (replace legacy Prompt1.txt)
- `bank/` — validated question JSONL (`qa.jsonl`, `qa-arith-di.jsonl`, `lr.jsonl`, `varc.jsonl`)
- `papers/` — assembled outputs (`mock-01.json`, `practice-15q.json`)
- `public/` — Pages publish boundary: `index.html` runner (Study/Exam/Simulation, paper picker, `?paper=<id>`) + `papers/` published set + `index.json` manifest
- `scripts/` — `banklib.py` (shared: mix-aware assembly, validation), `validate_paper.py`, `assemble_paper.py`, `migrate_legacy.py`
- `app/` — admin: Flask `server.py` (http://127.0.0.1:5057), `admin.html`, `llm.config.json` (LLM loop opt-in, default off)
- `config/exam.config.json` — time/marking/sections
- `config/topics.json` — topic taxonomy (buckets, labels, subtopics, aliases); manage in the admin Topics tab

## Setup
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Workflow (admin app, preferred)
1. `.\.venv\Scripts\python.exe app\server.py` → open http://127.0.0.1:5057
2. New paper tab: pick exam kind (mock/simulation/practice), a blueprint or a custom spec (count, subject, single-topic-or-mix, difficulty) → Assemble → preview → Publish. Each paper needs a unique Paper ID (auto-suggested; it becomes the `papers/<id>.json` filename) — reusing an ID is blocked unless you confirm the overwrite.
3. Take it in `public/index.html` (paper picker or `?paper=<id>`). Serve `public/` for full manifest support.
4. Add questions via the Questions tab (schema-validated) or the LLM tab (needs `app/llm.config.json` enabled with an OpenAI-compatible endpoint). The bank's <b>Used in</b> column shows which published paper each question appears in (with a used/never-used filter).

## Workflow (CLI)
1. Generate batches with `prompts/generator-system.md` + section prompt → append JSONL to `bank/` (use bucket names as `topic` for new seeds).
2. `.\.venv\Scripts\python.exe scripts\validate_paper.py papers\mock-01.json --blueprint blueprints\full-mock-60q.yaml`
3. `.\.venv\Scripts\python.exe scripts\assemble_paper.py --blueprint blueprints\full-mock-60q.yaml --bank bank --out papers\mock-02.json --seed 43`
4. Publish: copy to `public/papers/` and upsert `public/papers/index.json` (or use the admin Publish button).
5. Legacy: `scripts\migrate_legacy.py <old.json> --out bank\<section>.jsonl --section QA`
