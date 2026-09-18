# AGENT.md — IPMAT Mock System

Version: 3.9.0 | Canonical spec: IIMB IPMAT 60Q, 135 min (8100 s), +3 / −1 / 0 | Status: active

## 1. What this project is
Hybrid mock-generation system for IPMAT (IIMB pattern) with a local admin app:
LLM prompts generate topic batches → validator gates them into the bank →
assembler builds blueprint-driven papers (full mocks, sectionals, practice,
simulations) → `public/index.html` runner delivers Study/Exam/Simulation modes
with +3/−1 scoring. Admin UI (`app/admin.html` + Flask `app/server.py`) manages
bank, topics, blueprints, papers, config, and an opt-in LLM loop. `public/` is the Pages publish
boundary (Pages deploys `public/` only).

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
| Bank | `bank/` | validated source of truth (`qa.jsonl`, `qa-arith-di.jsonl`, `lr.jsonl`, `varc.jsonl`; `banklib` reads `**/*.jsonl`) |
| Assembler | `scripts/assemble_paper.py` → `scripts/banklib.py` | blueprint mix + difficulty_split → paper; balances answers 25% each; raises `BankShortage` with need/have details |
| Validator | `scripts/validate_paper.py` → `banklib.validate_all` | schema + +3/−1/0 + unique qids + blueprint counts/mix/difficulty + balance |
| Topic map | `banklib.TOPIC_BUCKET` | legacy QA topics → mix buckets (Arithmetic/Algebra/ModernMath_Geometry/DataInterpretation); LR/VARC seeds already use bucket names |
| Taxonomy | `config/topics.json` | single source of truth: section → bucket {label, subtopics, aliases}; managed via admin Topics tab / `/api/topics` (add/update/rename-with-migration/delete-if-unused); bank adds reject unknown topics |
| Migrator | `scripts/migrate_legacy.py` | legacy (+4/−1, `stem/answer`, Prompt1) → v2 |
| Runner | `public/index.html` | Study/Exam/Simulation modes; paper picker from `public/papers/index.json`; `?paper=<id\|file>`; Simulation = strict, review-after-submit |
| Public site | `public/landing.html`, `public/signup.html`, `public/signin.html` | landing (pattern band, modes, live bank/paper counts via `/api/health`+`/api/papers` with static fallbacks) → signup/signin (Flask-backed; static Pages deploys show a server-unreachable note) → runner |
| Manifest | `public/papers/index.json` | published set (id/title/file/kind/questions/time_sec) |
| Admin BE | `app/server.py` (:5057, 127.0.0.1) | `/api/bank|blueprints|assemble|papers/publish|usage|config|students/*|llm/*`; `/api/bank` filters `section|topic|subtopic|difficulty|q`; bank add rejects unknown subtopics with the bucket's valid list; paper breakdown (`GET /api/papers/<id>/breakdown`: difficulty/section/topic/subtopic splits, answer balance, integrity, blueprint expected-vs-actual) + unpublish (manifest only) + delete (manifest + both files); LLM loop gated by `app/llm.config.json` (`enabled`); publish rejects duplicate paper_id with 409 unless `overwrite:true`; `/api/usage` maps qid → manifest papers (+orphan paper files missing from the manifest); student signup (`POST /api/students/signup`, unique email 409, scrypt-hashed passwords in git-ignored `data/students.json`) + signin (`POST /api/students/signin`, generic 401) + admin list/delete/reset-password |
| Admin UI | `app/admin.html` | dashboard, bank browser+add (Used-in column + used/never-used filter, ⚠ flags paper files missing from the manifest; Subtopic column + filter, canonical tags enforced on add; section/difficulty colour pills: QA blue, LR amber, VARC green), blueprint manager (CRUD + dry-run vs bank), paper wizard (kind/count/subject/single-or-mix/difficulty, unique auto-suggested Paper ID, overwrite confirm, saved-file message), papers manager (per-paper breakdown, blueprint match, unpublish/delete), students manager (search/reset-pw/delete), LLM, config |
| Config | `config/exam.config.json` | time/marking/sections (marking locked +3/−1/0 by server) |

Data flow: batch (prompt) → validate → bank → assemble (seeded) → validate
vs blueprint → paper → runner. Reproduce any paper via blueprint/spec + seed (the seed shuffles each bucket's draw + difficulty-repair swaps in `banklib.assemble`; it is stored as the paper's `meta.seed` and shown in the Papers tab breakdown — bank edits reshuffle the draw).

## 4. Workflows
- Admin (preferred): `.\.venv\Scripts\python.exe app\server.py` → http://127.0.0.1:5057 — assemble via blueprint or wizard spec (kind/count/subject/single-topic-or-mix/difficulty), preview, publish to runner.
- CLI: `assemble_paper.py --blueprint blueprints/full-mock-60q.yaml --bank bank --out papers/mock-NN.json --seed <n>` then validate with `--blueprint`. Publish = copy validated paper to `public/papers/` + upsert `public/papers/index.json`.
- New questions: `prompts/` templates (or admin LLM tab when enabled); append JSONL to `bank/`; use bucket names as `topic` for new seeds (`Arithmetic`, `DataInterpretation`, …); validate.
- Topics: edit in admin Topics tab (subtopics/aliases) — renames migrate bank + blueprints; JSONL appends always newline-separated.
- Legacy import: `migrate_legacy.py <old.json> --out bank/<sec>.jsonl --section <QA|LR|VARC>`.
- Env: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

## 5. Rules for agents
- Never reintroduce +4/−1 or legacy-first schemas; keep `spec.time_sec: 8100`.
- Keep answer positions balanced (±2); keep qids unique (`<SEC>-<TOPIC>-<NNN>`).
- Official-sample styles to mirror: VARC RC + odd-one-out + para-jumble; LR
  arrangements / coded relations / ranking / series / cause-effect; QA with DI
  sets, Bayes, mixture, HCF/LCM, CI; image-based stems via `stimulus_image`.
- Update this file (bump version) when spec, schema, or architecture changes.
- Docs-with-feature (mandatory): every user-facing admin change ships its guide
  in the same edit — (a) a section in the Guide tab (`app/admin.html#t-guide`,
  anchor `g-<area>`), (b) a `.hint` paragraph on the touched tab itself
  explaining the workflow, (c) this file + `README.md` updated when behavior
  or workflows change. No feature is "done" without its guide.
