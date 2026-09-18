"""IPMAT admin backend (local only): bank + papers + config + opt-in LLM loop.

Run:  .\\.venv\\Scripts\\python.exe app\\server.py   ->  http://127.0.0.1:5057
Serves the admin UI at / and JSON APIs under /api/*.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import banklib  # noqa: E402

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
BANK_DIR = ROOT / "bank"
PAPERS_DIR = ROOT / "papers"
PUBLIC_PAPERS = ROOT / "public" / "papers"
CONFIG_PATH = ROOT / "config" / "exam.config.json"
LLM_CONFIG_PATH = APP_DIR / "llm.config.json"

QSCHEMA = json.loads((ROOT / "schemas" / "question.schema.json").read_text(encoding="utf-8"))

DEFAULT_CONFIG = {
    "time_sec": 8100,
    "marking": {"correct": 3, "wrong": -1, "skipped": 0},
    "sections": [
        {"code": "QA", "count": 30},
        {"code": "LR", "count": 15},
        {"code": "VARC", "count": 15},
    ],
    "answer_balance_tolerance": 2,
}

BANK_FILE = {"QA": "qa.jsonl", "LR": "lr.jsonl", "VARC": "varc.jsonl"}

app = Flask(__name__, static_folder=str(APP_DIR), static_url_path="")


def _read_json(path, default):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path, obj):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _pool():
    return banklib.load_bank(BANK_DIR)


# ---------------- pages ----------------

@app.get("/")
def index():
    return send_from_directory(str(APP_DIR), "admin.html")


# ---------------- bank ----------------

@app.get("/api/health")
def health():
    pool = _pool()
    return jsonify({"ok": True, "bank_questions": len(pool),
                    "stats": banklib.bank_stats(pool)})


@app.get("/api/bank")
def bank_list():
    pool = _pool()
    sec = request.args.get("section", "")
    topic = request.args.get("topic", "")
    diff = request.args.get("difficulty", "")
    q = (request.args.get("q", "") or "").lower()
    out = [x for x in pool
           if (not sec or x.get("section") == sec)
           and (not topic or banklib.bucket_of(x) == topic or x.get("topic") == topic)
           and (not diff or x.get("difficulty") == diff)
           and (not q or q in (x.get("stem", "") + x.get("qid", "")).lower())]
    return jsonify({"count": len(out), "questions": out})


@app.post("/api/bank")
def bank_add():
    q = request.get_json(force=True)
    errs = banklib.validate_schema({"questions": [q]}, QSCHEMA)
    if errs:
        return jsonify({"ok": False, "errors": errs}), 422
    pool = _pool()
    if any(x.get("qid") == q.get("qid") for x in pool):
        return jsonify({"ok": False, "errors": [f"duplicate qid {q.get('qid')}"]}), 422
    target = BANK_DIR / BANK_FILE.get(q.get("section"), "qa.jsonl")
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(q, ensure_ascii=False) + "\n")
    return jsonify({"ok": True, "qid": q.get("qid"), "file": target.name})


# ---------------- blueprints + assembly ----------------

@app.get("/api/blueprints")
def blueprints():
    import yaml
    out = []
    for f in sorted((ROOT / "blueprints").glob("*.yaml")):
        try:
            bp = yaml.safe_load(f.read_text(encoding="utf-8"))
            out.append({"file": f.name, "paper_id": bp.get("paper_id"),
                        "title": bp.get("title"), "kind": bp.get("kind"),
                        "sections": bp.get("sections", []),
                        "difficulty_split": bp.get("difficulty_split")})
        except Exception as e:
            out.append({"file": f.name, "error": str(e)})
    return jsonify({"blueprints": out})


@app.post("/api/assemble")
def assemble():
    """Assemble from a saved blueprint OR a wizard spec.

    Wizard spec: {kind, seed, sections:[{code,count,mix?}], difficulty_split?,
                  difficulties?:[Easy..], title?, paper_id?}
    """
    import yaml
    body = request.get_json(force=True) or {}
    seed = int(body.get("seed", 42))
    if body.get("blueprint"):
        bp_path = ROOT / "blueprints" / body["blueprint"]
        if not bp_path.exists():
            return jsonify({"ok": False, "errors": ["unknown blueprint"]}), 404
        bp = yaml.safe_load(bp_path.read_text(encoding="utf-8"))
    else:
        bp = {"paper_id": body.get("paper_id", "IPMAT-CUSTOM"),
              "title": body.get("title", "IPMAT Custom Paper"),
              "kind": body.get("kind", "full_mock"),
              "time_sec": int(body.get("time_sec", DEFAULT_CONFIG["time_sec"])),
              "marking": DEFAULT_CONFIG["marking"],
              "sections": body.get("sections", DEFAULT_CONFIG["sections"]),
              "difficulty_split": body.get("difficulty_split")}
    pool = _pool()
    if body.get("difficulties"):
        keep = set(body["difficulties"])
        pool = [x for x in pool if x.get("difficulty") in keep]
    try:
        paper, warnings = banklib.assemble(bp, pool, seed=seed)
    except banklib.BankShortage as e:
        return jsonify({"ok": False, "errors": [str(e)],
                        "shortage": e.details}), 422
    return jsonify({"ok": True, "paper": paper, "warnings": warnings})


# ---------------- papers / publish ----------------

def _manifest():
    return _read_json(PUBLIC_PAPERS / "index.json", {"papers": []})


@app.get("/api/papers")
def papers():
    return jsonify(_manifest())


@app.post("/api/papers/publish")
def publish():
    body = request.get_json(force=True) or {}
    paper = body.get("paper")
    if not paper or not paper.get("questions"):
        return jsonify({"ok": False, "errors": ["no paper supplied"]}), 422
    errs = banklib.validate_all(paper, QSCHEMA)
    if errs:
        return jsonify({"ok": False, "errors": errs}), 422
    pid = paper.get("paper_id", "IPMAT-PAPER")
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in pid)
    _write_json(PAPERS_DIR / f"{safe}.json", paper)
    _write_json(PUBLIC_PAPERS / f"{safe}.json", paper)
    man = _manifest()
    entry = {"id": pid, "title": paper.get("title", pid), "file": f"{safe}.json",
             "kind": paper.get("kind", "full_mock"),
             "questions": len(paper["questions"]),
             "time_sec": paper.get("spec", {}).get("time_sec", 8100)}
    man["papers"] = [e for e in man.get("papers", []) if e.get("id") != pid] + [entry]
    _write_json(PUBLIC_PAPERS / "index.json", man)
    return jsonify({"ok": True, "entry": entry})


# ---------------- config ----------------

@app.get("/api/config")
def config_get():
    return jsonify(_read_json(CONFIG_PATH, DEFAULT_CONFIG))


@app.post("/api/config")
def config_save():
    body = request.get_json(force=True) or {}
    if body.get("marking") != {"correct": 3, "wrong": -1, "skipped": 0}:
        return jsonify({"ok": False, "errors": ["marking must stay +3/-1/0"]}), 422
    _write_json(CONFIG_PATH, body)
    return jsonify({"ok": True})


# ---------------- LLM loop (opt-in) ----------------

def _llm_config():
    return _read_json(LLM_CONFIG_PATH,
                      {"enabled": False, "provider": "openai-compatible",
                       "base_url": "", "model": "", "api_key": ""})


@app.get("/api/llm/status")
def llm_status():
    cfg = _llm_config()
    return jsonify({"enabled": bool(cfg.get("enabled")),
                    "provider": cfg.get("provider", ""),
                    "model": cfg.get("model", ""),
                    "base_url": cfg.get("base_url", ""),
                    "has_key": bool(cfg.get("api_key"))})


@app.post("/api/llm/generate")
def llm_generate():
    cfg = _llm_config()
    if not cfg.get("enabled"):
        return jsonify({"ok": False, "errors": [
            "LLM loop is disabled. Enable it in app/llm.config.json first."]}), 403
    body = request.get_json(force=True) or {}
    section = (body.get("section") or "QA").lower()
    if section not in ("qa", "lr", "varc"):
        return jsonify({"ok": False, "errors": ["bad section"]}), 422
    n = int(body.get("count", 5))
    prompt_file = ROOT / "prompts" / f"{section}-batch.md"
    system_file = ROOT / "prompts" / "generator-system.md"
    try:
        tmpl = prompt_file.read_text(encoding="utf-8")
        system = system_file.read_text(encoding="utf-8")
    except Exception as e:
        return jsonify({"ok": False, "errors": [f"prompt files missing: {e}"]}), 500
    prompt = (tmpl.replace("[N]", str(n))
                   .replace("[DIFFICULTY]", body.get("difficulty", "Mixed"))
                   .replace("[TOPIC-MIX]", body.get("topic_mix", "blueprint mix")))
    import requests
    try:
        r = requests.post(cfg["base_url"].rstrip("/") + "/chat/completions",
                          headers={"Authorization": f"Bearer {cfg.get('api_key', '')}"},
                          json={"model": cfg.get("model"),
                                "messages": [{"role": "system", "content": system},
                                             {"role": "user", "content": prompt}]},
                          timeout=120)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return jsonify({"ok": False, "errors": [f"LLM call failed: {e}"]}), 502
    questions = _extract_questions(text)
    errs = banklib.validate_schema({"questions": questions}, QSCHEMA) if questions else ["no questions parsed"]
    saved = []
    if body.get("save") and questions and not errs:
        pool = _pool()
        have = {x.get("qid") for x in pool}
        target = BANK_DIR / BANK_FILE.get(questions[0].get("section"), "qa.jsonl")
        with target.open("a", encoding="utf-8") as f:
            for x in questions:
                if x.get("qid") in have:
                    continue
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
                saved.append(x.get("qid"))
    return jsonify({"ok": not errs, "questions": questions, "errors": errs,
                    "saved": saved, "raw": text[:4000]})


def _extract_questions(text):
    """Pull a JSON array (or JSONL lines) of question objects out of LLM text."""
    import re
    try:
        start = text.index("[")
        depth, end = 0, None
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end:
            obj = json.loads(text[start:end])
            if isinstance(obj, list):
                return [x for x in obj if isinstance(x, dict)]
    except Exception:
        pass
    out = []
    for line in text.splitlines():
        line = line.strip().removeprefix("```").removesuffix("```").strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                o = json.loads(line)
                if isinstance(o, dict) and "stem" in o:
                    out.append(o)
            except Exception:
                continue
    return out


if __name__ == "__main__":
    print("IPMAT admin on http://127.0.0.1:5057  (local only)")
    app.run(host="127.0.0.1", port=5057, debug=False)
