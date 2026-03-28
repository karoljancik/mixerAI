from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_job(job_path: Path) -> dict:
    if not job_path.exists():
        raise FileNotFoundError(f"Job manifest not found: {job_path}")

    with job_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description="MixerAI job inspector")
    parser.add_argument("--job", required=True, help="Path to a mix-job.json manifest")
    args = parser.parse_args()

    job = load_job(Path(args.job))

    print("MixerAI Python worker")
    print(f"job_id={job['Id']}")
    print(f"title={job['Title']}")
    print(f"status={job['Status']}")
    print("next_step=implement feature extraction, beat alignment and model inference")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
