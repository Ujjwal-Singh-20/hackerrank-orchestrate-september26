"""emit: write output.csv + a per-run manifest so any run is reproducible:
config fingerprint, dataset fingerprint, timestamp, provider."""

from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from schemas import OutputRow

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_CSV = ROOT / "output.csv"
MANIFEST_PATH = ROOT / "code" / "emit" / "run_manifest.json"


def _file_fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def dataset_fingerprint() -> dict:
    files = ["requests.csv", "financial_profiles.csv", "financial_events.csv",
             "exchange_rates.csv", "request_payment_options.csv",
             "messages.csv", "images.csv"]
    out = {}
    for name in files:
        p = ROOT / "dataset" / name
        out[name] = _file_fingerprint(p) if p.exists() else "missing"
    return out


def write_output(rows: Iterable[OutputRow]) -> Path:
    rows = sorted(rows, key=lambda r: r.request_id)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        f.write(OutputRow.HEADER + "\n")
        for row in rows:
            cells = row.as_csv_row()
            cells = [("" if c is None else c) for c in cells]
            f.write(",".join(_csv_escape(c) for c in cells) + "\n")
    return OUT_CSV


def _csv_escape(value: str) -> str:
    if any(ch in value for ch in (",", '"', "\n")):
        return '"' + value.replace('"', '""') + '"'
    return value


def write_manifest(config_fingerprint: str, provider: str, n_rows: int,
                   notes: str = "") -> Path:
    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config_fingerprint": config_fingerprint,
        "dataset_fingerprints": dataset_fingerprint(),
        "perception_provider": provider,
        "rows_written": n_rows,
        "notes": notes,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    return MANIFEST_PATH


def config_fingerprint() -> str:
    import config
    cls_attrs = {k: getattr(config.Config, k) for k in dir(config.Config)
                 if k.isupper()}
    blob = json.dumps(cls_attrs, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]