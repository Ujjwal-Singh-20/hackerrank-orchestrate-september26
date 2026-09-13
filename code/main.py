"""Buy or Wait? — main entry point.

Usage:
    python3 code/main.py            # route all requests, write output.csv

Reads dataset/, writes output.csv (repo root) plus a per-run manifest
(code/emit/run_manifest.json) for reproducibility.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import emit
import pipeline


def main() -> int:
    t0 = time.time()
    config.validate()
    rows = pipeline.route_all()
    if not rows:
        print("ERROR: no rows produced", file=sys.stderr)
        return 1
    out = emit.write_output(rows)
    manifest = emit.write_manifest(
        config_fingerprint=emit.config_fingerprint(),
        provider=config.get().PERCEPTION_PROVIDER,
        n_rows=len(rows),
        notes=f"routed {len(rows)} requests in {time.time()-t0:.1f}s")
    print(f"wrote {len(rows)} rows -> {out}")
    print(f"manifest -> {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())