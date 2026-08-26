#!/usr/bin/env python3
"""Re-file Langfuse dataset items from one combined dataset into one per grade.

The browser extractor originally wrote every curriculum design into a single
dataset. cbc-api reads one dataset per grade (``get_dataset(name=grade_slug)``),
so nothing in the combined dataset is visible to it.

This copies the items across. The extracted text is reused as-is — nothing is
re-scraped from Google Drive, so a run costs only API calls.

Dry run by default. Nothing is written until you pass --apply.

    python3 migrate_langfuse_datasets.py                 # show the plan
    python3 migrate_langfuse_datasets.py --apply         # write it
    python3 migrate_langfuse_datasets.py --apply --only grade-10
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE_DATASET = "CBC_Research_Curriculum_Designs"

# The level a document was listed under on kicd.ac.ke -> the grade dataset(s)
# it belongs in. Lower Primary is one combined design covering Grades 1-3, so it
# is filed under each of them.
LEVEL_TO_GRADES: dict[str, list[str]] = {
    "pre-primary 1 (pp1)": ["grade-pp1"],
    "pre-primary 1": ["grade-pp1"],
    "pre-primary 2 (pp2)": ["grade-pp2"],
    "pre-primary 2": ["grade-pp2"],
    "lower primary (grades 1-3)": ["grade-1", "grade-2", "grade-3"],
    "lower primary": ["grade-1", "grade-2", "grade-3"],
    "diploma in teacher education": ["grade-dte"],
}
for _n in range(1, 13):
    LEVEL_TO_GRADES[f"grade {_n}"] = [f"grade-{_n}"]

_GRADE_IN_TEXT = re.compile(r"\bgrade\s*(\d{1,2})\b", re.IGNORECASE)


def load_env() -> None:
    for path in (os.path.join(HERE, "..", ".env"), os.path.join(HERE, ".env")):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def grades_for(item: dict) -> list[str]:
    """Which grade dataset(s) this item belongs in."""
    inp = item.get("input") if isinstance(item.get("input"), dict) else {}
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}

    level = str(inp.get("level") or meta.get("level") or "").strip().lower()
    if level in LEVEL_TO_GRADES:
        return LEVEL_TO_GRADES[level]

    # "Grade 10" inside a level string that does not match exactly.
    match = _GRADE_IN_TEXT.search(level)
    if match and 1 <= int(match.group(1)) <= 12:
        return [f"grade-{int(match.group(1))}"]

    # Fall back to the document title, which usually names the grade:
    # "Chemistry Grade 12 - March 2026.pdf"
    title = str(inp.get("title") or meta.get("name") or "")
    match = _GRADE_IN_TEXT.search(title)
    if match and 1 <= int(match.group(1)) <= 12:
        return [f"grade-{int(match.group(1))}"]

    if "diploma" in title.lower() or "diploma" in level:
        return ["grade-dte"]
    if re.search(r"\bpp\s*2\b|pre-?primary\s*2", title, re.IGNORECASE):
        return ["grade-pp2"]
    if re.search(r"\bpp\s*1\b|pre-?primary", title, re.IGNORECASE):
        return ["grade-pp1"]

    return []


class Langfuse:
    def __init__(self, host: str, pk: str, sk: str):
        self.host = host.rstrip("/")
        self.auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"{self.host}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {self.auth}",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}

    def list_items(self, dataset: str) -> list[dict]:
        """Every item in a dataset, following pagination."""
        items: list[dict] = []
        page = 1
        while True:
            encoded = urllib.parse.quote(dataset, safe="")
            payload = self._request(
                "GET", f"/api/public/dataset-items?datasetName={encoded}&page={page}&limit=50"
            )
            batch = payload.get("data") or payload.get("items") or []
            if not batch:
                break
            items.extend(batch)
            meta = payload.get("meta") or {}
            total_pages = meta.get("totalPages")
            if total_pages is not None and page >= int(total_pages):
                break
            if len(batch) < 50:
                break
            page += 1
        return items

    def upsert_item(self, dataset: str, item_id: str, item: dict) -> dict:
        inp = dict(item.get("input") or {})
        meta = dict(item.get("metadata") or {})
        inp["grade"] = dataset
        meta["grade"] = dataset
        meta["migrated_from"] = SOURCE_DATASET
        return self._request("POST", "/api/public/dataset-items", {
            "id": item_id,
            "datasetName": dataset,
            "input": inp,
            "expectedOutput": item.get("expectedOutput") or item.get("expected_output") or "",
            "metadata": meta,
        })


def main() -> int:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write (default is a dry run)")
    ap.add_argument("--source", default=SOURCE_DATASET)
    ap.add_argument("--only", default="", help="restrict to one grade slug, e.g. grade-10")
    ap.add_argument("--host", default=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"))
    ap.add_argument("--public-key", default=os.environ.get("LANGFUSE_PUBLIC_KEY", ""))
    ap.add_argument("--secret-key", default=os.environ.get("LANGFUSE_SECRET_KEY", ""))
    args = ap.parse_args()

    if not args.public_key or not args.secret_key:
        sys.exit("Missing Langfuse keys. Set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY in .env.")

    client = Langfuse(args.host, args.public_key, args.secret_key)

    print(f"Reading '{args.source}' from {args.host} …")
    items = client.list_items(args.source)
    print(f"  {len(items)} item(s) found\n")

    plan: list[tuple[str, str, dict]] = []
    unmapped: list[str] = []

    for item in items:
        inp = item.get("input") if isinstance(item.get("input"), dict) else {}
        file_id = str(inp.get("file_id") or item.get("id") or "").strip()
        targets = grades_for(item)
        if not targets:
            unmapped.append(str(inp.get("title") or item.get("id")))
            continue
        if args.only:
            targets = [t for t in targets if t == args.only]
        for grade in targets:
            plan.append((grade, f"{grade}__{file_id}", item))

    counts = Counter(grade for grade, _id, _it in plan)
    for grade in sorted(counts, key=lambda g: (len(g), g)):
        print(f"  {grade:12} {counts[grade]:3} item(s)")
    print(f"\n  total writes: {len(plan)}")

    if unmapped:
        print(f"\n  ⚠️  {len(unmapped)} item(s) could not be assigned a grade:")
        for title in unmapped[:10]:
            print(f"       {title}")
        if len(unmapped) > 10:
            print(f"       … and {len(unmapped) - 10} more")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write these.")
        return 0

    print("\nWriting …")
    ok = failed = 0
    for grade, item_id, item in plan:
        try:
            client.upsert_item(grade, item_id, item)
            ok += 1
            if ok % 25 == 0:
                print(f"  {ok}/{len(plan)}")
        except urllib.error.HTTPError as err:
            failed += 1
            print(f"  !! {item_id}: HTTP {err.code} {err.read().decode('utf-8', 'replace')[:160]}")
        except Exception as err:  # noqa: BLE001
            failed += 1
            print(f"  !! {item_id}: {err}")

    print(f"\n{ok} written, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
