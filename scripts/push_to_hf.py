"""Publish the incident corpus to the Hugging Face Hub.

    export HF_TOKEN=hf_...
    python scripts/push_to_hf.py [--repo your-username/geohazard-incidents]

Pushes incidents.jsonl plus the dataset card. The corpus is small and hand
curated; the card carries the limitations, and this script refuses to publish
without it, because a dataset about warning failures should not itself ship
without its caveats.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "data" / "hf_dataset"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.getenv("PRAHARI_HF_DATASET", "prahari/geohazard-incidents"))
    ap.add_argument("--private", action="store_true")
    args = ap.parse_args()

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    if not token:
        print("HF_TOKEN is not set. Get one at https://huggingface.co/settings/tokens")
        return 1

    jsonl = DATASET_DIR / "incidents.jsonl"
    card = DATASET_DIR / "README.md"
    if not jsonl.exists():
        print(f"missing {jsonl}")
        return 1
    if not card.exists():
        print("refusing to publish without the dataset card (README.md).")
        return 1

    rows = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"corpus: {len(rows)} incidents")
    print(f"  rainfall-driven      : {sum(r['rain_driven'] for r in rows)}")
    print(f"  seismically detectable: {sum(r['seismically_detectable'] for r in rows)}")
    print(f"  warning failed        : {sum(r['warning_failed'] for r in rows)}")

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("\npip install huggingface-hub")
        return 1

    api = HfApi(token=token)
    api.create_repo(args.repo, repo_type="dataset", exist_ok=True, private=args.private)
    api.upload_folder(
        folder_path=str(DATASET_DIR),
        repo_id=args.repo,
        repo_type="dataset",
        commit_message="Publish Himalayan & Brahmaputra geohazard incident corpus",
    )
    print(f"\npublished: https://huggingface.co/datasets/{args.repo}")
    print("point the app at it with:  export PRAHARI_HF_DATASET=" + args.repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
