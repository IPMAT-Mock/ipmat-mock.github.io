"""Validate a paper JSON against schemas + blueprint checks."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import banklib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) < 2:
        print("usage: validate_paper.py <paper.json> [--blueprint <yaml>]")
        sys.exit(2)
    paper_path = sys.argv[1]
    bp_path = None
    if "--blueprint" in sys.argv:
        bp_path = sys.argv[sys.argv.index("--blueprint") + 1]
    paper = json.loads(pathlib.Path(paper_path).read_text(encoding="utf-8"))
    qschema = json.loads((ROOT / "schemas" / "question.schema.json").read_text(encoding="utf-8"))
    try:
        errors = banklib.validate_schema(paper, qschema)
    except ImportError:
        errors = ["jsonschema not installed (pip install -r requirements.txt)"]
    errors += banklib.validate_canonical(paper)

    if bp_path:
        import yaml
        bp = yaml.safe_load(pathlib.Path(bp_path).read_text(encoding="utf-8"))
        errors += banklib.validate_blueprint(paper, bp)

    if errors:
        print("FAIL")
        [print(" -", e) for e in errors]
        sys.exit(1)
    from collections import Counter
    qs = paper.get("questions", [])
    print(f"OK: {len(qs)} questions, sections {dict(Counter(q.get('section') for q in qs))}, "
          f"answers {dict(Counter(q.get('answer_index') for q in qs))}")


if __name__ == "__main__":
    main()
