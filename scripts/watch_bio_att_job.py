"""Watch a bio-attendance background job until it finishes.

Usage:
    python scripts/watch_bio_att_job.py <job_id> [--co-id 1] [--host http://localhost:8000]
                                                 [--subdomain sls] [--interval 2]

Reads the access_token cookie from the env var ACCESS_TOKEN if set;
otherwise relies on BYPASS_AUTH on the server.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

import requests


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("job_id")
    p.add_argument("--co-id", default="1")
    p.add_argument("--host", default="http://localhost:8000")
    p.add_argument("--subdomain", default="sls")
    p.add_argument("--interval", type=float, default=2.0)
    args = p.parse_args()

    url = f"{args.host}/api/hrmsMasters/bio_att_excel_status/{args.job_id}"
    params = {"co_id": args.co_id}
    headers = {"x-forwarded-host": f"{args.subdomain}.vowerp.co.in"}
    cookies: dict[str, str] = {}
    token = os.environ.get("ACCESS_TOKEN")
    if token:
        cookies["access_token"] = token

    print(f"Watching job {args.job_id} at {url} (every {args.interval}s)\n")
    last_line = ""
    while True:
        try:
            r = requests.get(url, params=params, headers=headers, cookies=cookies, timeout=10)
        except requests.RequestException as e:
            print(f"\n[network] {e}")
            time.sleep(args.interval)
            continue

        if r.status_code != 200:
            print(f"\n[http {r.status_code}] {r.text[:200]}")
            return 1

        data: dict[str, Any] = r.json()
        status = data.get("status", "?")
        line = (
            f"status={status:<10} processed={data.get('processed', 0):>6} "
            f"inserted={data.get('inserted', 0):>6} dup={data.get('duplicates', 0):>6} "
            f"invalid={data.get('invalid', 0):>6} total={data.get('total', 0):>6}"
        )
        if line != last_line:
            print(f"\r{line}", end="", flush=True)
            last_line = line

        if status == "completed":
            print("\n\nDone.")
            return 0
        if status == "failed":
            print(f"\n\nFAILED: {data.get('error')}")
            return 2

        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
