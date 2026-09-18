"""Assemble a paper from bank JSONL files using a blueprint YAML.
Usage: assemble_paper.py --blueprint blueprints/full-mock-60q.yaml --bank bank --out papers/mock-01.json [--seed 42]
Bank layout: bank/<qa|lr|varc>.jsonl or bank/**/*.jsonl, one v2 question per line.
"""
import argparse, json, pathlib, random
import yaml

SEC = {"QA": "QA", "LR": "LR", "VARC": "VARC"}

def load_bank(bank: pathlib.Path):
    qs = []
    for f in sorted(bank.rglob("*.jsonl")) + sorted(bank.rglob("*.json")):
        try:
            if f.suffix == ".jsonl":
                for line in f.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        qs.append(json.loads(line))
            else:
                d = json.loads(f.read_text(encoding="utf-8"))
                qs += d if isinstance(d, list) else d.get("questions", [d])
        except Exception as e:
            print(f"warn: skip {f}: {e}")
    return qs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blueprint", required=True)
    ap.add_argument("--bank", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    bp = yaml.safe_load(pathlib.Path(a.blueprint).read_text(encoding="utf-8"))
    pool = load_bank(pathlib.Path(a.bank))
    rnd = random.Random(a.seed)
    picked, used = [], set()
    for sec in bp.get("sections", []):
        code, n = sec["code"], sec["count"]
        cand = [q for q in pool if q.get("section") == code and q.get("qid") not in used]
        if len(cand) < n:
            raise SystemExit(f"bank short for {code}: need {n}, have {len(cand)}")
        rnd.shuffle(cand)
        sel = cand[:n]
        for q in sel:
            used.add(q["qid"])
        picked.extend(sel)
    # Balance answer positions by rotating options (uniform target).
    target = len(picked) // 4
    need = {0: target, 1: target, 2: target, 3: target}
    for i in range(len(picked) % 4):
        need[i] += 1
    have = {0: 0, 1: 0, 2: 0, 3: 0}
    for q in picked:
        cur = int(q.get("answer_index", 0))
        # choose rotation k -> (cur+k)%4 with remaining need, prefer k=0
        choices = sorted(range(4), key=lambda k: (need[(cur + k) % 4] - have[(cur + k) % 4] <= 0, k != 0, k))
        k = next(k for k in choices if need[(cur + k) % 4] - have[(cur + k) % 4] > 0)
        if k:
            opts = q["options"]
            q["options"] = opts[-k:] + opts[:-k] if k else opts
            q["answer_index"] = (cur + k) % 4
        have[int(q["answer_index"])] += 1
    paper = {
        "paper_id": bp.get("paper_id", "IPMAT-MOCK"),
        "title": bp.get("title", "IPMAT Mock"),
        "kind": bp.get("kind", "full_mock"),
        "spec": {"total_questions": len(picked), "time_sec": 8100,
                 "marking": {"correct": 3, "wrong": -1, "skipped": 0}},
        "sections": [{"code": s["code"], "count": s["count"]} for s in bp.get("sections", [])],
        "questions": picked,
    }
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(paper, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out} ({len(picked)} questions)")

if __name__ == "__main__":
    main()
