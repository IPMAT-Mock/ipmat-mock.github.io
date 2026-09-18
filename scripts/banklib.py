"""Shared question-bank library (importable by CLI scripts and the admin server).

Bank layout: bank/<qa|lr|varc>.jsonl (one v2 question per line); *.json also read.
Blueprints may carry per-section `mix` (topic-bucket -> count) and a global
`difficulty_split`. Legacy QA topics predate the mix keys, so TOPIC_BUCKET maps
them onto buckets; LR/VARC seed topics already equal their bucket names.
"""
import copy
import json
import pathlib
import random
from collections import Counter

SECTIONS = ("QA", "LR", "VARC")

# Legacy "Quantitative Aptitude - X" topic -> blueprint mix bucket.
QA_TOPIC_BUCKET = {
    "Quantitative Aptitude - Quadratic Equations": "Algebra",
    "Quantitative Aptitude - Linear Equations": "Algebra",
    "Quantitative Aptitude - Logarithms": "Algebra",
    "Quantitative Aptitude - Arithmetic Progressions": "Algebra",
    "Quantitative Aptitude - Geometric Progressions": "Algebra",
    "Quantitative Aptitude - Functions & Graphs": "Algebra",
    "Quantitative Aptitude - Inequalities": "Algebra",
    "Quantitative Aptitude - Permutations & Combinations": "ModernMath_Geometry",
    "Quantitative Aptitude - Probability": "ModernMath_Geometry",
    "Quantitative Aptitude - Number System": "ModernMath_Geometry",
}

TOPIC_BUCKET = {"QA": QA_TOPIC_BUCKET, "LR": {}, "VARC": {}}

ROOT = pathlib.Path(__file__).resolve().parent.parent
TAXONOMY_PATH = ROOT / "config" / "topics.json"
_taxonomy_cache = None


def _default_taxonomy():
    """Built-in fallback when config/topics.json is missing (keeps CLI usable)."""
    return {
        "QA": {"label": "Quantitative Aptitude", "buckets": {
            "Arithmetic": {"label": "Arithmetic", "subtopics": [], "aliases": []},
            "Algebra": {"label": "Algebra", "subtopics": [],
                        "aliases": sorted(QA_TOPIC_BUCKET)},
            "ModernMath_Geometry": {"label": "Modern Math & Geometry",
                                    "subtopics": [], "aliases": []},
            "DataInterpretation": {"label": "Data Interpretation",
                                   "subtopics": [], "aliases": []}}},
        "LR": {"label": "Logical Reasoning", "buckets": {
            b: {"label": b, "subtopics": [], "aliases": []}
            for b in ("Arrangements", "Series_Coding", "CriticalReasoning")}},
        "VARC": {"label": "Verbal Ability & Reading Comprehension", "buckets": {
            b: {"label": b, "subtopics": [], "aliases": []}
            for b in ("ReadingComprehension", "VerbalLogic", "Grammar", "Vocabulary")}},
    }


def load_taxonomy(path=None, refresh=False):
    """Load config/topics.json (cached); fall back to built-ins if missing."""
    global _taxonomy_cache
    if _taxonomy_cache is not None and not refresh and path is None:
        return _taxonomy_cache
    p = pathlib.Path(path) if path else TAXONOMY_PATH
    try:
        tax = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        tax = _default_taxonomy()
    if path is None and not refresh:
        _taxonomy_cache = tax
    return tax


def taxonomy_buckets(taxonomy=None):
    """{section: [bucket, ...]} from the taxonomy."""
    tax = taxonomy or load_taxonomy()
    return {s: list(tax.get(s, {}).get("buckets", {})) for s in SECTIONS
            if s in tax}


class BankShortage(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def load_bank(bank_dir):
    """Read every .jsonl/.json under bank_dir into a list of question dicts."""
    bank_dir = pathlib.Path(bank_dir)
    qs = []
    for f in sorted(bank_dir.rglob("*.jsonl")) + sorted(bank_dir.rglob("*.json")):
        try:
            if f.suffix == ".jsonl":
                for line in f.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        qs.append(json.loads(line))
            else:
                d = json.loads(f.read_text(encoding="utf-8"))
                qs += d if isinstance(d, list) else d.get("questions", [d])
        except Exception as e:  # keep going; report the skip
            print(f"warn: skip {f}: {e}")
    return qs


def bucket_of(q, taxonomy=None):
    """Blueprint mix bucket for a bank question.

    A question's `topic` resolves to a bucket when it equals the bucket name
    or one of its taxonomy aliases (legacy QA names). Unknown topics fall
    through as-is so validators can flag them instead of crashing assembly.
    """
    sec, topic = q.get("section"), q.get("topic")
    tax = taxonomy or load_taxonomy()
    for bucket, info in tax.get(sec, {}).get("buckets", {}).items():
        if topic == bucket or topic in (info.get("aliases") or []):
            return bucket
    if topic in (TOPIC_BUCKET.get(sec) or {}):  # built-in fallback map
        return TOPIC_BUCKET[sec][topic]
    # LR/VARC seeds (and new backfill) already use bucket names as topics.
    return topic


def unmapped_topics(pool, taxonomy=None):
    """Topics in the bank that match no taxonomy bucket/alias (need attention)."""
    tax = taxonomy or load_taxonomy()
    known = {(s, b) for s in SECTIONS
             for b in tax.get(s, {}).get("buckets", {})}
    known |= {(s, a) for s in SECTIONS
              for b, i in tax.get(s, {}).get("buckets", {}).items()
              for a in (i.get("aliases") or [])}
    bad = Counter()
    for q in pool:
        if (q.get("section"), q.get("topic")) not in known:
            bad[(q.get("section"), q.get("topic"))] += 1
    return [{"section": s, "topic": t, "count": n} for (s, t), n in sorted(bad.items())]


def bank_stats(pool):
    """Nested counts: section -> bucket -> difficulty -> n (for the admin UI)."""
    stats = {}
    for q in pool:
        s = stats.setdefault(q.get("section", "?"), {})
        b = s.setdefault(bucket_of(q), Counter())
        b[q.get("difficulty", "?")] += 1
    return stats


def assemble(bp, pool, seed=42):
    """Pick questions per blueprint mix + difficulty_split.

    Returns (paper_dict, warnings). Raises BankShortage with details
    {section, bucket, need, have} when the bank cannot satisfy the mix.
    """
    rnd = random.Random(seed)
    picked, used, warnings = [], set(), []

    for sec in bp.get("sections", []):
        code, n = sec["code"], sec["count"]
        mix = sec.get("mix") or {}
        if mix:
            for bucket, bn in mix.items():
                cand = [q for q in pool
                        if q.get("section") == code and bucket_of(q) == bucket
                        and q.get("qid") not in used]
                if len(cand) < bn:
                    raise BankShortage(
                        f"bank short for {code}/{bucket}: need {bn}, have {len(cand)}",
                        {"section": code, "bucket": bucket,
                         "need": bn, "have": len(cand)})
                rnd.shuffle(cand)
                for q in cand[:bn]:
                    used.add(q["qid"])
                    picked.append(copy.deepcopy(q))
        else:  # no mix: plain section count (legacy blueprints)
            cand = [q for q in pool
                    if q.get("section") == code and q.get("qid") not in used]
            if len(cand) < n:
                raise BankShortage(
                    f"bank short for {code}: need {n}, have {len(cand)}",
                    {"section": code, "bucket": None, "need": n, "have": len(cand)})
            rnd.shuffle(cand)
            for q in cand[:n]:
                used.add(q["qid"])
                picked.append(copy.deepcopy(q))

    _repair_difficulty(bp, pool, picked, used, rnd, warnings)
    _balance_answers(picked, bp)

    marking = bp.get("marking", {"correct": 3, "wrong": -1, "skipped": 0})
    paper = {
        "paper_id": bp.get("paper_id", "IPMAT-MOCK"),
        "title": bp.get("title", "IPMAT Mock"),
        "kind": bp.get("kind", "full_mock"),
        "spec": {"total_questions": len(picked),
                 "time_sec": bp.get("time_sec", 8100),
                 "marking": marking},
        "sections": [{"code": s["code"], "count": s["count"]}
                     for s in bp.get("sections", [])],
        "questions": picked,
        "meta": {"seed": seed, "warnings": warnings},
    }
    return paper, warnings


def _repair_difficulty(bp, pool, picked, used, rnd, warnings):
    """Swap same-section+bucket substitutes so difficulty_split is met."""
    want = Counter(bp.get("difficulty_split") or {})
    if not want:
        return
    by_id = {q.get("qid"): q for q in pool}
    for _ in range(100):
        have = Counter(q.get("difficulty") for q in picked)
        over = [d for d in want if have[d] > want[d]]
        under = [d for d in want if have[d] < want[d]]
        if not over or not under:
            break
        done = False
        for do in over:
            for du in under:
                idxs = [i for i, q in enumerate(picked)
                        if q.get("difficulty") == do]
                rnd.shuffle(idxs)
                for i in idxs:
                    q = picked[i]
                    sub = next(
                        (c for c in pool
                         if c.get("section") == q.get("section")
                         and bucket_of(c) == bucket_of(q)
                         and c.get("difficulty") == du
                         and c.get("qid") not in used),
                        None)
                    if sub is None:
                        continue
                    used.discard(q["qid"])
                    used.add(sub["qid"])
                    picked[i] = copy.deepcopy(sub)
                    done = True
                    break
                if done:
                    break
            if done:
                break
        if not done:
            break
    have = Counter(q.get("difficulty") for q in picked)
    for d in want:
        if have[d] != want[d]:
            warnings.append(
                f"difficulty {d}: want {want[d]}, got {have[d]} (bank spread insufficient)")


def _balance_answers(picked, bp):
    """Rotate options so answer_index positions are uniform (in place)."""
    target = len(picked) // 4
    need = {0: target, 1: target, 2: target, 3: target}
    for i in range(len(picked) % 4):
        need[i] += 1
    have = {0: 0, 1: 0, 2: 0, 3: 0}
    for q in picked:
        cur = int(q.get("answer_index", 0))
        choices = sorted(range(4),
                         key=lambda k: (need[(cur + k) % 4] - have[(cur + k) % 4] <= 0,
                                        k != 0, k))
        k = next(k for k in choices
                 if need[(cur + k) % 4] - have[(cur + k) % 4] > 0)
        if k:
            opts = q["options"]
            q["options"] = opts[-k:] + opts[:-k]
            q["answer_index"] = (cur + k) % 4
        have[int(q["answer_index"])] += 1


# ---------------- validation (importable) ----------------

def validate_schema(paper, qschema):
    """Validate each question against question.schema.json -> [errors]."""
    import jsonschema
    errors = []
    for i, q in enumerate(paper.get("questions", [])):
        try:
            jsonschema.validate(q, qschema)
        except Exception as e:
            errors.append(f"Q#{i+1} {q.get('qid', '?')}: {e.message}")
    return errors


def validate_canonical(paper):
    """Spec/dupes/sections/answer-balance checks (no blueprint needed)."""
    errors = []
    spec = paper.get("spec", {})
    if spec.get("marking") != {"correct": 3, "wrong": -1, "skipped": 0}:
        errors.append(f"marking must be +3/-1/0, got {spec.get('marking')}")
    qs = paper.get("questions", [])
    qids = [q.get("qid") for q in qs]
    if len(qids) != len(set(qids)):
        errors.append("duplicate qids found")
    secs = Counter(q.get("section") for q in qs)
    for s in secs:
        if s not in SECTIONS:
            errors.append(f"bad section {s}")
    ans = Counter(q.get("answer_index") for q in qs)
    if ans and (max(ans.values()) - min(ans.values()) > 2):
        errors.append(f"answer imbalance {dict(ans)} (tolerance 2)")
    return errors


def validate_blueprint(paper, bp):
    """Blueprint checks: time, section counts, mix buckets, difficulty_split."""
    errors = []
    spec = paper.get("spec", {})
    if "time_sec" in bp and spec.get("time_sec") != bp["time_sec"]:
        errors.append(
            f"spec.time_sec must be {bp['time_sec']}, got {spec.get('time_sec')}")
    qs = paper.get("questions", [])
    secs = Counter(q.get("section") for q in qs)
    for sec in bp.get("sections", []):
        want, got = sec["count"], secs.get(sec["code"], 0)
        if want != got:
            errors.append(f"blueprint {sec['code']}: want {want}, got {got}")
        for bucket, bn in (sec.get("mix") or {}).items():
            got_b = sum(1 for q in qs
                        if q.get("section") == sec["code"] and bucket_of(q) == bucket)
            if bn != got_b:
                errors.append(
                    f"blueprint {sec['code']}/{bucket}: want {bn}, got {got_b}")
    want_d = Counter(bp.get("difficulty_split") or {})
    if want_d:
        have_d = Counter(q.get("difficulty") for q in qs)
        for d in want_d:
            if want_d[d] != have_d.get(d, 0):
                errors.append(
                    f"blueprint difficulty {d}: want {want_d[d]}, got {have_d.get(d, 0)}")
    return errors


def validate_all(paper, qschema, bp=None):
    errors = validate_schema(paper, qschema)
    errors += validate_canonical(paper)
    if bp:
        errors += validate_blueprint(paper, bp)
    return errors
