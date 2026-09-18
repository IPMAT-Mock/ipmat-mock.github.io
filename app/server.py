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


@app.get("/public/<path:name>")
def public_files(name):
    """Serve the test runner + published papers so ?paper=<id> links work."""
    return send_from_directory(str(ROOT / "public"), name)


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
    tax = _taxonomy()
    known = {b for b in tax.get(q.get("section"), {}).get("buckets", {})}
    known |= {a for b, i in tax.get(q.get("section"), {}).get("buckets", {}).items()
              for a in (i.get("aliases") or [])}
    if q.get("topic") not in known:
        return jsonify({"ok": False, "errors": [
            f"unknown topic '{q.get('topic')}' for {q.get('section')}. " +
            f"Valid: {sorted(known) or 'none — define buckets in the Topics tab first'}"]}), 422
    target = BANK_DIR / BANK_FILE.get(q.get("section"), "qa.jsonl")
    target.parent.mkdir(parents=True, exist_ok=True)
    _append_bank(target, q)
    return jsonify({"ok": True, "qid": q.get("qid"), "file": target.name})


def _append_bank(target, q):
    """Append one question JSONL-line, safe when the last line lacks \\n."""
    prefix = ""
    if target.exists() and target.stat().st_size:
        with target.open("rb") as f:
            f.seek(-1, 2)
            if f.read(1) != b"\n":  # last line unterminated -> separate it
                prefix = "\n"
    with target.open("a", encoding="utf-8") as f:
        f.write(prefix + json.dumps(q, ensure_ascii=False) + "\n")


# ---------------- blueprints + assembly ----------------

BP_FILE_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9\-_]*\.yaml$")
BP_KINDS = ("full_mock", "sectional", "practice", "simulation")


def _validate_blueprint(bp, tax=None):
    """Return [errors] for a blueprint dict (does not touch the bank)."""
    errs = []
    if not isinstance(bp, dict):
        return ["blueprint must be an object"]
    if not (bp.get("paper_id") or "").strip():
        errs.append("paper_id is required")
    if not (bp.get("title") or "").strip():
        errs.append("title is required")
    if bp.get("kind") not in BP_KINDS:
        errs.append(f"kind must be one of {', '.join(BP_KINDS)}")
    try:
        t = int(bp.get("time_sec", 8100))
        if t <= 0:
            errs.append("time_sec must be > 0")
    except Exception:
        errs.append("time_sec must be an integer")
    if bp.get("marking", {"correct": 3, "wrong": -1, "skipped": 0}) != \
            {"correct": 3, "wrong": -1, "skipped": 0}:
        errs.append("marking must stay +3/-1/0")
    secs = bp.get("sections")
    if not isinstance(secs, list) or not secs:
        errs.append("sections must be a non-empty list")
        return errs
    tax = tax or _taxonomy()
    total = 0
    seen_codes = set()
    for s in secs:
        code = s.get("code")
        if code not in ("QA", "LR", "VARC"):
            errs.append(f"bad section code {code!r} (use QA/LR/VARC)")
            continue
        if code in seen_codes:
            errs.append(f"duplicate section {code}")
        seen_codes.add(code)
        try:
            n = int(s.get("count", 0))
        except Exception:
            errs.append(f"{code}: count must be an integer")
            continue
        if n <= 0:
            errs.append(f"{code}: count must be > 0")
            continue
        total += n
        mix = s.get("mix")
        if mix:
            if not isinstance(mix, dict):
                errs.append(f"{code}: mix must be an object")
                continue
            known = set(tax.get(code, {}).get("buckets", {}))
            for b, bn in mix.items():
                if b not in known:
                    errs.append(f"{code}/{b}: unknown bucket (valid: {sorted(known)})")
                try:
                    if int(bn) < 0:
                        errs.append(f"{code}/{b}: mix count must be >= 0")
                except Exception:
                    errs.append(f"{code}/{b}: mix count must be an integer")
            if sum(int(v) for v in mix.values()
                   if isinstance(v, int) or str(v).isdigit()) != n:
                errs.append(f"{code}: mix sums to {sum(mix.values())}, "
                            f"must equal count {n}")
    ds = bp.get("difficulty_split")
    if ds:
        if not isinstance(ds, dict) or \
                any(d not in ("Easy", "Medium", "Hard") for d in ds):
            errs.append("difficulty_split keys must be Easy/Medium/Hard")
        else:
            try:
                if sum(int(v) for v in ds.values()) != total:
                    errs.append(f"difficulty_split sums to {sum(ds.values())}, "
                                f"must equal total {total}")
            except Exception:
                errs.append("difficulty_split values must be integers")
    return errs


def _blueprint_summary(path):
    import yaml
    try:
        bp = yaml.safe_load(path.read_text(encoding="utf-8"))
        total = sum(int(s.get("count", 0)) for s in bp.get("sections", []))
        return {"file": path.name, "paper_id": bp.get("paper_id"),
                "title": bp.get("title"), "kind": bp.get("kind"),
                "time_sec": bp.get("time_sec", 8100),
                "total": total,
                "sections": bp.get("sections", []),
                "difficulty_split": bp.get("difficulty_split"),
                "answer_balance": bp.get("answer_balance")}
    except Exception as e:
        return {"file": path.name, "error": str(e)}


@app.get("/api/blueprints")
def blueprints():
    out = [_blueprint_summary(f)
           for f in sorted((ROOT / "blueprints").glob("*.yaml"))]
    return jsonify({"blueprints": out})


@app.get("/api/blueprints/<name>")
def blueprint_detail(name):
    import yaml
    if not BP_FILE_RE.match(name or ""):
        return jsonify({"ok": False, "errors": ["bad blueprint filename"]}), 422
    path = ROOT / "blueprints" / name
    if not path.exists():
        return jsonify({"ok": False, "errors": ["blueprint not found"]}), 404
    try:
        bp = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify({"ok": False, "errors": [f"YAML error: {e}"]}), 422
    return jsonify({"ok": True, "file": name, "blueprint": bp,
                    "raw": path.read_text(encoding="utf-8")})


@app.post("/api/blueprints")
def blueprints_manage():
    """Manage blueprints. Actions:
    save {file, blueprint} — create or overwrite (validated)
    duplicate {file, new_file} — copy
    delete {file} — remove (no questions reference blueprints directly)
    """
    import yaml
    body = request.get_json(force=True) or {}
    action = body.get("action", "")
    fname = (body.get("file") or "").strip()

    if action == "save":
        bp = body.get("blueprint")
        if not fname or not BP_FILE_RE.match(fname):
            return jsonify({"ok": False, "errors": [
                "file must match [a-z0-9][a-z0-9-_]*.yaml"]}), 422
        errs = _validate_blueprint(bp)
        if errs:
            return jsonify({"ok": False, "errors": errs}), 422
        path = ROOT / "blueprints" / fname
        path.write_text(yaml.safe_dump(bp, sort_keys=False, allow_unicode=True),
                        encoding="utf-8")
        return jsonify({"ok": True, "file": fname,
                        "summary": _blueprint_summary(path)})

    if action == "duplicate":
        new_file = (body.get("new_file") or "").strip()
        if not BP_FILE_RE.match(fname) or not BP_FILE_RE.match(new_file):
            return jsonify({"ok": False, "errors": ["bad filename(s)"]}), 422
        src = ROOT / "blueprints" / fname
        dst = ROOT / "blueprints" / new_file
        if not src.exists():
            return jsonify({"ok": False, "errors": ["source not found"]}), 404
        if dst.exists():
            return jsonify({"ok": False, "errors": [
                f"{new_file} already exists"]}), 422
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return jsonify({"ok": True, "file": new_file,
                        "summary": _blueprint_summary(dst)})

    if action == "delete":
        if not BP_FILE_RE.match(fname):
            return jsonify({"ok": False, "errors": ["bad filename"]}), 422
        path = ROOT / "blueprints" / fname
        if not path.exists():
            return jsonify({"ok": False, "errors": ["blueprint not found"]}), 404
        if len(list((ROOT / "blueprints").glob("*.yaml"))) <= 1:
            return jsonify({"ok": False, "errors": [
                "cannot delete the last blueprint"]}), 422
        path.unlink()
        return jsonify({"ok": True, "deleted": fname})
    return jsonify({"ok": False, "errors": [f"unknown action {action}"]}), 422


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


# ---------------- topics ----------------

TAXONOMY_PATH = ROOT / "config" / "topics.json"
BUCKET_RE = __import__("re").compile(r"^[A-Za-z][A-Za-z0-9_]{1,39}$")


def _taxonomy():
    return banklib.load_taxonomy(refresh=True)


def _save_taxonomy(tax):
    _write_json(TAXONOMY_PATH, tax)
    banklib.load_taxonomy(refresh=True)


def _bucket_usage(pool, tax):
    use = {}
    for q in pool:
        key = (q.get("section"), banklib.bucket_of(q, tax))
        use[key] = use.get(key, 0) + 1
    return use


@app.get("/api/topics")
def topics_get():
    tax = _taxonomy()
    pool = _pool()
    use = _bucket_usage(pool, tax)
    out = {}
    for sec, info in tax.items():
        out[sec] = {"label": info.get("label", sec), "buckets": {}}
        for b, bi in info.get("buckets", {}).items():
            out[sec]["buckets"][b] = {
                "label": bi.get("label", b),
                "subtopics": bi.get("subtopics", []),
                "aliases": bi.get("aliases", []),
                "questions": use.get((sec, b), 0)}
    return jsonify({"taxonomy": out,
                    "unmapped": banklib.unmapped_topics(pool, tax)})


@app.post("/api/topics")
def topics_post():
    """Manage buckets. Actions:
    add {section, bucket, label?, subtopics?, aliases?}
    update {section, bucket, label?, subtopics?, aliases?}
    rename {section, bucket, new_bucket} (migrates bank topics + blueprint mix keys)
    delete {section, bucket} (blocked when questions or blueprints use it)
    """
    import yaml
    body = request.get_json(force=True) or {}
    action = body.get("action", "")
    sec = body.get("section", "")
    bucket = body.get("bucket", "")
    tax = _taxonomy()
    if sec not in tax:
        return jsonify({"ok": False, "errors": [f"unknown section {sec}"]}), 422
    buckets = tax[sec].setdefault("buckets", {})

    def _clean_list(v):
        return [x.strip() for x in (v or []) if x and x.strip()]

    if action in ("add", "update"):
        if not BUCKET_RE.match(bucket or ""):
            return jsonify({"ok": False, "errors": [
                "bucket key must start with a letter, letters/digits/_ only, max 40 chars"]}), 422
        if action == "add" and bucket in buckets:
            return jsonify({"ok": False, "errors": [f"{bucket} already exists"]}), 422
        if action == "update" and bucket not in buckets:
            return jsonify({"ok": False, "errors": [f"{bucket} not found"]}), 422
        cur = buckets.get(bucket, {})
        buckets[bucket] = {"label": (body.get("label") or "").strip() or bucket,
                           "subtopics": _clean_list(body.get("subtopics")),
                           "aliases": _clean_list(body.get("aliases"))}
        # aliases must not collide with other buckets/aliases in the section
        seen = {}
        for b, bi in buckets.items():
            for name in [b] + bi.get("aliases", []):
                if name in seen:
                    buckets[bucket] = cur  # roll back
                    return jsonify({"ok": False, "errors": [
                        f"name clash: '{name}' already used by {seen[name]}"]}), 422
                seen[name] = b
        _save_taxonomy(tax)
        return jsonify({"ok": True, "bucket": bucket})

    if action == "rename":
        new = body.get("new_bucket", "")
        if bucket not in buckets:
            return jsonify({"ok": False, "errors": [f"{bucket} not found"]}), 422
        if not BUCKET_RE.match(new or "") or new in buckets:
            return jsonify({"ok": False, "errors": [f"bad or taken name {new}"]}), 422
        moved_q, moved_bp = 0, 0
        for f in sorted(BANK_DIR.rglob("*.jsonl")):
            lines = f.read_text(encoding="utf-8").splitlines()
            changed = False
            for i, line in enumerate(lines):
                if not line.strip():
                    continue
                q = json.loads(line)
                if q.get("section") == sec and q.get("topic") == bucket:
                    q["topic"] = new
                    lines[i] = json.dumps(q, ensure_ascii=False)
                    moved_q += 1
                    changed = True
            if changed:
                f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        for f in sorted((ROOT / "blueprints").glob("*.yaml")):
            bp = yaml.safe_load(f.read_text(encoding="utf-8"))
            dirty = False
            for s in bp.get("sections", []):
                if s.get("code") == sec and isinstance(s.get("mix"), dict) \
                        and bucket in s["mix"]:
                    s["mix"][new] = s["mix"].pop(bucket)
                    dirty = True
            if dirty:
                f.write_text(yaml.safe_dump(bp, sort_keys=False, allow_unicode=True),
                             encoding="utf-8")
                moved_bp += 1
        buckets[new] = buckets.pop(bucket)
        _save_taxonomy(tax)
        return jsonify({"ok": True, "renamed": f"{bucket} -> {new}",
                        "questions_moved": moved_q, "blueprints_touched": moved_bp})

    if action == "delete":
        if bucket not in buckets:
            return jsonify({"ok": False, "errors": [f"{bucket} not found"]}), 422
        pool = _pool()
        nq = sum(1 for q in pool if q.get("section") == sec
                 and banklib.bucket_of(q, tax) == bucket)
        bps = [f.name for f in sorted((ROOT / "blueprints").glob("*.yaml"))
               if bucket in str(f.read_text(encoding="utf-8"))]
        if nq or bps:
            return jsonify({"ok": False, "errors": [
                f"in use: {nq} bank question(s)" +
                (f", blueprints: {', '.join(bps)}" if bps else "") +
                " — move or delete them first"]}), 422
        buckets.pop(bucket)
        _save_taxonomy(tax)
        return jsonify({"ok": True, "deleted": bucket})
    return jsonify({"ok": False, "errors": [f"unknown action {action}"]}), 422


# ---------------- papers / publish ----------------

def _manifest():
    return _read_json(PUBLIC_PAPERS / "index.json", {"papers": []})


@app.get("/api/papers")
def papers():
    return jsonify(_manifest())


@app.get("/api/usage")
def usage():
    """Map each bank qid -> published papers containing it [{id, title}].

    Keyed off the runner manifest (what ?paper=<id> resolves), not the
    paper file's own paper_id — the two can drift (e.g. practice-15q).
    Paper files missing from the manifest are reported as orphans.
    """
    man = _manifest()
    entries = man.get("papers", [])
    by_file = {e.get("file"): e for e in entries}
    use, orphans = {}, []
    for f in sorted(PAPERS_DIR.glob("*.json")):
        try:
            paper = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        m = by_file.get(f.name)
        if m:
            pid, title, orphan = m.get("id"), m.get("title", m.get("id")), False
        else:
            pid = paper.get("paper_id") or f.stem
            title = paper.get("title") or pid
            orphan = True
            if f.name not in orphans:
                orphans.append(f.name)
        for q in paper.get("questions", []) or []:
            qid = q.get("qid")
            if not qid:
                continue
            use.setdefault(qid, [])
            if not any(e["id"] == pid for e in use[qid]):
                use[qid].append({"id": pid, "title": title,
                                 "orphan": orphan})
    return jsonify({"usage": use, "papers": len(entries), "orphans": orphans})


@app.post("/api/papers/publish")
def publish():
    body = request.get_json(force=True) or {}
    paper = body.get("paper")
    if not paper or not paper.get("questions"):
        return jsonify({"ok": False, "errors": ["no paper supplied"]}), 422
    errs = banklib.validate_all(paper, QSCHEMA)
    if errs:
        return jsonify({"ok": False, "errors": errs}), 422
    pid = (paper.get("paper_id") or "IPMAT-PAPER").strip()
    if not pid:
        return jsonify({"ok": False, "errors": ["paper_id is required"]}), 422
    paper["paper_id"] = pid
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in pid)
    man = _manifest()
    clash = next((e for e in man.get("papers", []) if e.get("id") == pid), None)
    if clash and not body.get("overwrite"):
        return jsonify({"ok": False, "errors": [
            f"paper_id '{pid}' already published as '{clash.get('title')}' "
            f"({clash.get('file')}) — change the Paper ID or confirm overwrite"],
            "collision": clash}), 409
    _write_json(PAPERS_DIR / f"{safe}.json", paper)
    _write_json(PUBLIC_PAPERS / f"{safe}.json", paper)
    entry = {"id": pid, "title": paper.get("title", pid), "file": f"{safe}.json",
             "kind": paper.get("kind", "full_mock"),
             "questions": len(paper["questions"]),
             "time_sec": paper.get("spec", {}).get("time_sec", 8100)}
    man["papers"] = [e for e in man.get("papers", []) if e.get("id") != pid] + [entry]
    _write_json(PUBLIC_PAPERS / "index.json", man)
    return jsonify({"ok": True, "entry": entry, "overwrote": bool(clash),
                    "files": [f"papers/{safe}.json",
                              f"public/papers/{safe}.json"]})


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
    raw = _read_json(LLM_CONFIG_PATH,
                     {"enabled": False, "provider": "openai-compatible",
                      "base_url": "", "model": "", "api_key": ""})
    return _normalize_llm_config(raw)


def _normalize_llm_config(raw):
    """Merge legacy flat config into the providers block (read-side only).

    Legacy shape: {enabled, provider: 'openai-compatible', base_url, model,
    api_key}. New shape: {enabled, provider: 'openai'|'gemini',
    providers: {openai: {...}, gemini: {...}}}. Legacy values win when the
    providers block lacks them, so old files keep working untouched.
    """
    raw = dict(raw or {})
    providers = {k: dict(v or {}) for k, v in (raw.get("providers") or {}).items()}
    providers.setdefault("openai", {})
    providers.setdefault("gemini", {})
    if raw.get("base_url") or raw.get("model") or raw.get("api_key"):
        leg = providers["openai"]
        leg.setdefault("base_url", raw.get("base_url") or "https://api.openai.com/v1")
        leg.setdefault("model", raw.get("model") or "")
        leg.setdefault("api_key", raw.get("api_key") or "")
    providers["openai"].setdefault("base_url", "https://api.openai.com/v1")
    providers["gemini"].setdefault("model", "gemini-2.0-flash")
    prov = (raw.get("provider") or "openai").lower()
    if prov == "openai-compatible":
        prov = "openai"
    if prov not in providers:
        prov = "openai"
    raw["provider"] = prov
    raw["providers"] = providers
    return raw


def _active_provider_cfg(cfg, name=None):
    """Resolve (name, pconf, error) for the requested or default provider."""
    name = (name or cfg.get("provider") or "openai").lower()
    if name == "openai-compatible":
        name = "openai"
    pconf = (cfg.get("providers") or {}).get(name)
    if pconf is None:
        return name, None, f"unknown provider '{name}' (use openai or gemini)"
    if not (pconf.get("model") or "").strip():
        return name, None, f"no model set for '{name}' in app/llm.config.json"
    if not (pconf.get("api_key") or "").strip():
        return name, None, f"no api_key set for '{name}' in app/llm.config.json"
    if name == "openai" and not (pconf.get("base_url") or "").strip():
        return name, None, "no base_url set for 'openai' in app/llm.config.json"
    return name, pconf, None


@app.get("/api/llm/status")
def llm_status():
    cfg = _llm_config()
    out = {"enabled": bool(cfg.get("enabled")), "provider": cfg.get("provider", "")}
    provs = {}
    for name, p in (cfg.get("providers") or {}).items():
        provs[name] = {"model": p.get("model", ""),
                       "has_key": bool(p.get("api_key"))}
        if name == "openai":
            provs[name]["base_url"] = p.get("base_url", "")
    out["providers"] = provs
    return jsonify(out)


def _openai_request(pconf, system, user):
    """(url, headers, body) for an OpenAI-compatible chat-completions call."""
    return (pconf["base_url"].rstrip("/") + "/chat/completions",
            {"Authorization": f"Bearer {pconf.get('api_key', '')}"},
            {"model": pconf.get("model"),
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": user}]})


def _gemini_request(pconf, system, user):
    """(url, headers, body) for a Gemini generateContent call.

    System prompt goes in systemInstruction, batch prompt in contents;
    responseMimeType JSON keeps the reply parseable by _extract_questions.
    """
    return (f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{pconf.get('model')}:generateContent",
            {"x-goog-api-key": pconf.get("api_key", ""),
             "Content-Type": "application/json"},
            {"systemInstruction": {"parts": [{"text": system}]},
             "contents": [{"parts": [{"text": user}]}],
             "generationConfig": {"responseMimeType": "application/json",
                                  "temperature": 0.7}})


def _gemini_text(payload):
    """Join the text parts of a generateContent response."""
    cands = payload.get("candidates") or []
    if not cands:
        raise RuntimeError(f"no candidates in Gemini reply: {str(payload)[:300]}")
    parts = ((cands[0].get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if not text.strip():
        raise RuntimeError(f"empty text in Gemini reply: {str(payload)[:300]}")
    return text


def _build_llm_prompt(section, n, difficulty, topic_mix):
    """Build the EXACT (system, user) prompts sent to the LLM.

    Single source of truth: preview endpoint and generate endpoint both use
    this, so what you see in the UI is byte-identical to what is sent.
    """
    section = (section or "qa").lower()
    if section not in ("qa", "lr", "varc"):
        return None, None, "bad section (use qa, lr, varc)"
    prompt_file = ROOT / "prompts" / f"{section}-batch.md"
    system_file = ROOT / "prompts" / "generator-system.md"
    try:
        tmpl = prompt_file.read_text(encoding="utf-8")
        system = system_file.read_text(encoding="utf-8")
    except Exception as e:
        return None, None, f"prompt files missing: {e}"
    user = (tmpl.replace("[N]", str(n))
                 .replace("[DIFFICULTY]", difficulty or "Mixed")
                 .replace("[TOPIC-MIX]", topic_mix or "blueprint mix"))
    return system, user, None


@app.get("/api/llm/prompt")
def llm_prompt():
    """Preview the exact prompts that generate would send (no LLM call)."""
    system, user, err = _build_llm_prompt(
        request.args.get("section", "qa"),
        int(request.args.get("count", 5) or 5),
        request.args.get("difficulty", "Mixed"),
        request.args.get("topic_mix", "blueprint mix"))
    if err:
        return jsonify({"ok": False, "errors": [err]}), 422
    return jsonify({"ok": True, "system": system, "user": user})


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
    system, user, err = _build_llm_prompt(
        section, n, body.get("difficulty", "Mixed"),
        body.get("topic_mix", "blueprint mix"))
    if err:
        return jsonify({"ok": False, "errors": [err]}), 500
    import requests
    prov_name, pconf, perr = _active_provider_cfg(cfg, body.get("provider"))
    if perr:
        return jsonify({"ok": False, "errors": [perr]}), 422
    try:
        if prov_name == "gemini":
            url, headers, payload = _gemini_request(pconf, system, user)
            r = requests.post(url, headers=headers, json=payload, timeout=120)
            r.raise_for_status()
            text = _gemini_text(r.json())
        else:
            url, headers, payload = _openai_request(pconf, system, user)
            r = requests.post(url, headers=headers, json=payload, timeout=120)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return jsonify({"ok": False, "errors": [f"LLM call failed ({prov_name}): {e}"]}), 502
    questions = _extract_questions(text)
    errs = banklib.validate_schema({"questions": questions}, QSCHEMA) if questions else ["no questions parsed"]
    saved = []
    if body.get("save") and questions and not errs:
        pool = _pool()
        have = {x.get("qid") for x in pool}
        target = BANK_DIR / BANK_FILE.get(questions[0].get("section"), "qa.jsonl")
        for x in questions:
            if x.get("qid") in have:
                continue
            _append_bank(target, x)
            saved.append(x.get("qid"))
    return jsonify({"ok": not errs, "questions": questions, "errors": errs,
                    "saved": saved, "raw": text[:4000], "provider": prov_name,
                    "sent": {"system": system, "user": user}})


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
