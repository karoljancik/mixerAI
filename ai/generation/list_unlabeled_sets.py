from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


KNOWN_LABELS = {"liquid", "deep", "exclude"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List manifests that do not yet have an explicit style label."
    )
    parser.add_argument("--manifests-dir", required=True, help="Directory with set manifests")
    parser.add_argument("--style-map-path", required=True, help="JSON file mapping set_id to liquid|deep|exclude")
    parser.add_argument("--output-path", help="Optional output text file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifests_dir = Path(args.manifests_dir)
    style_map = load_style_map(Path(args.style_map_path))

    unlabeled = []
    for manifest_path in sorted(manifests_dir.glob("*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        set_id = str(manifest.get("set_id", "")).strip()
        if set_id and set_id not in style_map:
            unlabeled.append(set_id)

    if args.output_path:
        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(unlabeled) + ("\n" if unlabeled else ""), encoding="utf-8")
        print(f"output_path={output_path}")

    print(f"unlabeled_sets={len(unlabeled)}")
    for set_id in unlabeled:
        print_safe(set_id)

    return 0


def load_style_map(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(key): str(value).strip().lower()
        for key, value in payload.items()
        if str(value).strip().lower() in KNOWN_LABELS
    }


def print_safe(value: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    safe_text = value.encode(encoding, errors="backslashreplace").decode(encoding)
    print(safe_text)


if __name__ == "__main__":
    raise SystemExit(main())
