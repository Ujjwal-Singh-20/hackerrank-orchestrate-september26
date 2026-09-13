"""Gemini OCR extraction for dataset/media/images (replaces local tesseract/GLM-OCR).

Reads GEMINI_API_KEY (and optional GEMINI_MODEL, default gemini-2.5-flash)
from .env in the repo root. No other credentials are needed. The key is read
from the environment file at runtime and never logged or committed.

Usage:
    .venv/bin/python code/ocr_gemini.py             # all 16 images
    .venv/bin/python code/ocr_gemini.py image_14    # single image
"""
import base64
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "dataset" / "media" / "images"
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = (
    "You are reading a financial document image (receipt, bill, payslip, "
    "invoice or statement). Extract: (1) the total amount billed/paid/net, "
    "with its currency, as a single number; (2) the document date if shown; "
    "(3) a one-line description. Reply ONLY with JSON: "
    '{"amount": <number or null>, "currency": "<code>", "date": "<YYYY-MM-DD or null>", '
    '"description": "<line>"}'
)


def load_env(path=ROOT / ".env"):
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def ask(model, key, image_path):
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    body = json.dumps({
        "contents": [{"parts": [
            {"text": PROMPT},
            {"inline_data": {"mime_type": "image/png", "data": b64}},
        ]}],
        "generationConfig": {"temperature": 0.0},
    }).encode()
    req = urllib.request.Request(
        API.format(model=model),
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {"error": text}


def main(ids=None):
    env = load_env()
    key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY not set: paste it into .env at the repo root.")
    model = env.get("GEMINI_MODEL") or "gemini-2.5-flash"
    ids = ids or sorted(p.stem for p in IMG_DIR.glob("image_*.png"))
    for iid in ids:
        img = IMG_DIR / f"{iid}.png"
        try:
            res = ask(model, key, img)
        except Exception as e:  # noqa: BLE001
            res = {"error": str(e)}
        print(f"===={iid}====")
        print(json.dumps(res, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:] or None)