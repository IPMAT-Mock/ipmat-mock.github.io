# AGENT.md — IPMAT Mock System

Version: 2.0.0 | Canonical spec: IIMB IPMAT 60Q, 135 min (8100 s), +3 / −1 / 0 | Status: active

## 1. What this project is
Hybrid mock-generation system for IPMAT (IIMB pattern): LLM prompts generate
topic batches → validator gates them into a question bank → assembler builds
blueprint-driven papers (full mocks, sectionals, practice) → `index.html`
runner delivers Study/Exam modes with +3/−1 scoring.

## 2. Canonical spec (do not drift)
- 60 MCQs = 30 QA + 15 LR + 15 VARC; 135 min; no sectional timer; CBT.
- Marking: +3 correct, −1 wrong, 0 skipped. 4 options, exactly one correct.
- v2 question fields: `qid, section (QA|LR|VARC), topic, difficulty,
  stem, options[4], answer_index, hint, solution` (+ optional
  `passage, stimulus_image, time_sec`). Legacy aliases
  (`answer, id, explanation, scenario, question_text…`) are auto-normalized
  by the runner and `migrate_legacy.py` — never author new content in them.

## 3. Architecture
```
prompts/ ──generate──▶ bank/*.jsonl ──assemble──▶ papers/*.json ──render──▶ index.html
   │                       │                         │
   │ schemas/*.schema.json │ blueprints/*.yaml       │ validate_paper.py (gates every step)
   └───────────────────────┴─────────────────────────┘
```
| Component | Path | Role |
|---|---|---|
| Schemas | `schemas/` | v2 contracts for questions/papers |
| Blueprints | `blueprints/` | target counts, topic mix, difficulty split, answer tolerance |
| Prompts | `prompts/` | `generator-system.md` + QA/LR/VARC/DI batch templates |
| Bank | `bank/` | validated source of truth (`qa/lr/varc.jsonl`) |
| Assembler | `scripts/assemble_paper.py` | blueprint → paper; balances answer positions 25% each |
| Validator | `scripts/validate_paper.py` | schema + 8100s + +3/−1/0 + unique qids + blueprint counts + balance |
| Migrator | `scripts/migrate_legacy.py` | legacy (+4/−1, `stem/answer`, Prompt1) → v2 |
| Runner | `index.html` | Study/Exam modes; auto-loads `papers/mock-01.json`, legacy fallback |

Data flow: batch (prompt) → validate → bank → assemble (seeded) → validate
vs blueprint → paper → runner. Reproduce any paper via blueprint + seed.

## 4. Workflows
- New mock: `assemble_paper.py --blueprint blueprints/full-mock-60q.yaml --bank bank --out papers/mock-NN.json --seed <n>` then validate with `--blueprint`.
- New questions: use `prompts/` templates; append JSONL to `bank/`; validate.
- Legacy import: `migrate_legacy.py <old.json> --out bank/<sec>.jsonl --section <QA|LR|VARC>`.
- Env: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

## 5. Rules for agents
- Never reintroduce +4/−1 or legacy-first schemas; keep `spec.time_sec: 8100`.
- Keep answer positions balanced (±2); keep qids unique (`<SEC>-<TOPIC>-<NNN>`).
- Official-sample styles to mirror: VARC RC + odd-one-out + para-jumble; LR
  arrangements / coded relations / ranking / series / cause-effect; QA with DI
  sets, Bayes, mixture, HCF/LCM, CI; image-based stems via `stimulus_image`.
- Update this file (bump version) when spec, schema, or architecture changes.
