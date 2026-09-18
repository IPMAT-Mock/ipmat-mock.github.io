"""Assemble a paper from bank JSONL files using a blueprint YAML.
Usage: assemble_paper.py --blueprint blueprints/full-mock-60q.yaml --bank bank --out papers/mock-01.json [--seed 42]
Bank layout: bank/<qa|lr|varc>.jsonl or bank/**/*.jsonl, one v2 question per line.
Honors per-section `mix` buckets and global `difficulty_split` (see banklib).
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import yaml
import banklib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blueprint", required=True)
    ap.add_argument("--bank", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    bp = yaml.safe_load(pathlib.Path(a.blueprint).read_text(encoding="utf-8"))
    pool = banklib.load_bank(pathlib.Path(a.bank))
    try:
        paper, warnings = banklib.assemble(bp, pool, seed=a.seed)
    except banklib.BankShortage as e:
        raise SystemExit(f"bank short: {e}")
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(paper, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out} ({len(paper['questions'])} questions)")
    for w in warnings:
        print(f"warn: {w}")


if __name__ == "__main__":
    main()
