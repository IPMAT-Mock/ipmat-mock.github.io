"""Validate a paper JSON against schemas + blueprint checks."""
import json, sys, pathlib
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent

def load(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))

def main():
    if len(sys.argv) < 2:
        print("usage: validate_paper.py <paper.json> [--blueprint <yaml>]"); sys.exit(2)
    paper_path = sys.argv[1]
    bp_path = None
    if "--blueprint" in sys.argv:
        bp_path = sys.argv[sys.argv.index("--blueprint") + 1]
    paper = load(paper_path)
    qschema = load(ROOT / "schemas" / "question.schema.json")
    errors = []
    try:
        import jsonschema
        for i, q in enumerate(paper.get("questions", [])):
            try:
                jsonschema.validate(q, qschema)
            except Exception as e:
                errors.append(f"Q#{i+1} {q.get('qid','?')}: {e.message}")
    except ImportError:
        errors.append("jsonschema not installed (pip install -r requirements.txt)")

    spec = paper.get("spec", {})
    if spec.get("time_sec") != 8100:
        errors.append(f"spec.time_sec must be 8100, got {spec.get('time_sec')}")
    if spec.get("marking") != {"correct": 3, "wrong": -1, "skipped": 0}:
        errors.append(f"marking must be +3/-1/0, got {spec.get('marking')}")
    qs = paper.get("questions", [])
    qids = [q.get("qid") for q in qs]
    if len(qids) != len(set(qids)):
        errors.append("duplicate qids found")
    secs = Counter(q.get("section") for q in qs)
    for s, n in secs.items():
        if s not in ("QA", "LR", "VARC"):
            errors.append(f"bad section {s}")
    ans = Counter(q.get("answer_index") for q in qs)
    if ans and (max(ans.values()) - min(ans.values()) > 2):
        errors.append(f"answer imbalance {dict(ans)} (tolerance 2)")

    if bp_path:
        import yaml
        bp = yaml.safe_load(pathlib.Path(bp_path).read_text(encoding="utf-8"))
        for sec in bp.get("sections", []):
            want, got = sec["count"], secs.get(sec["code"], 0)
            if want != got:
                errors.append(f"blueprint {sec['code']}: want {want}, got {got}")

    if errors:
        print("FAIL"); [print(" -", e) for e in errors]; sys.exit(1)
    print(f"OK: {len(qs)} questions, sections {dict(secs)}, answers {dict(ans)}")

if __name__ == "__main__":
    main()
