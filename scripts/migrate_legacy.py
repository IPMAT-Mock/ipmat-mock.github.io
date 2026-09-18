"""Migrate legacy samples (v1/v0) to v2 canonical schema (+3/-1).
Handles: legacy {id,stem,options[],answer,explanation,scenario} and
Prompt1 {question_id,subject,question_text,options[{option_text,is_correct}],hint,detailed_explanation}.
Usage: migrate_legacy.py <in.json> --out bank/qa.jsonl [--section QA]
"""
import argparse, json, pathlib

def norm_legacy(q, i, section):
    if "stem" in q and "options" in q and isinstance(q["options"], list):
        opts = q["options"]
        ans = q.get("answer", q.get("answer_index", 0))
        return {"qid": q.get("id", f"{section}-MIG-{i+1:03d}"), "section": section,
                "topic": str(q.get("scenario", "QA-General"))[:80], "subtopic": str(q.get("task", "")),
                "difficulty": q.get("difficulty", "Medium"), "marks": {"correct": 3, "wrong": -1, "skipped": 0},
                "time_sec": 120, "stem": q["stem"], "options": opts, "answer_index": int(ans),
                "hint": "", "solution": q.get("explanation", "") or "See options."}
    opts = q.get("options", [])
    texts = [o.get("option_text", "") if isinstance(o, dict) else str(o) for o in opts]
    ans = next((k for k, o in enumerate(opts) if isinstance(o, dict) and o.get("is_correct")), 0)
    return {"qid": q.get("question_id", f"{section}-MIG-{i+1:03d}"), "section": section,
            "topic": q.get("topic") or q.get("subject", "QA-General"), "subtopic": q.get("sub_topic", ""),
            "difficulty": "Medium", "marks": {"correct": 3, "wrong": -1, "skipped": 0},
            "time_sec": int(q.get("allotted_time_seconds", 120)), "stem": q.get("question_text", ""),
            "options": texts, "answer_index": int(ans), "hint": q.get("hint", ""),
            "solution": q.get("detailed_explanation", "") or "See options."}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp"); ap.add_argument("--out", required=True)
    ap.add_argument("--section", default="QA")
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.inp).read_text(encoding="utf-8"))
    qs = d if isinstance(d, list) else d.get("questions", [])
    out = [norm_legacy(q, i, a.section) for i, q in enumerate(qs)]
    p = pathlib.Path(a.out); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(q, ensure_ascii=False) for q in out), encoding="utf-8")
    print(f"Migrated {len(out)} -> {p}")

if __name__ == "__main__":
    main()
