# IPMAT Mock System (IIMB pattern)

Canonical spec: 60 MCQs (30 QA + 15 LR + 15 VARC), 135 min (8100 s),
marking +3 correct / −1 wrong / 0 skipped. See `exam scheme/`.

## Layout
- `schemas/` — v2 question + paper JSON schemas
- `blueprints/` — full-mock-60q, sectional QA/LR/VARC, mixed practice
- `prompts/` — generator system + QA/LR/VARC/DI batch prompts (replace legacy Prompt1.txt)
- `bank/` — validated question JSONL (`qa.jsonl`, `lr.jsonl`, `varc.jsonl`)
- `papers/` — assembled outputs (`mock-01.json`, `practice-15q.json`)
- `scripts/` — `validate_paper.py`, `assemble_paper.py`, `migrate_legacy.py`
- `index.html` — test runner (Study/Exam modes, auto-loads `papers/mock-01.json`)

## Setup
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Workflow (hybrid: prompts + assembler)
1. Generate batches with `prompts/generator-system.md` + section prompt → append JSONL to `bank/`.
2. `.\.venv\Scripts\python.exe scripts\validate_paper.py papers\mock-01.json --blueprint blueprints\full-mock-60q.yaml`
3. `.\.venv\Scripts\python.exe scripts\assemble_paper.py --blueprint blueprints\full-mock-60q.yaml --bank bank --out papers\mock-02.json --seed 43`
4. Open `index.html` (or serve the folder) to take the test.
5. Legacy: `scripts\migrate_legacy.py <old.json> --out bank\<section>.jsonl --section QA`
