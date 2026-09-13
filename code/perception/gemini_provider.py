"""Optional Gemini-backed perception provider. Only used when
config.PERCEPTION_PROVIDER == 'gemini' (needs GEMINI_API_KEY in .env)."""

from __future__ import annotations
import base64
import json
import re
import urllib.request

import config
from errors import ExtractionError
from schemas import Amendment, Dataset


class GeminiPerception:
    """Calls Google Generative Language REST API. No vendor SDK; the key is
    read from .env / environment and never logged."""

    API = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "{model}:generateContent")

    def __init__(self):
        self._key = self._load_key()

    @staticmethod
    def _load_key() -> str:
        env_path = config.get()  # ensure validate() ran
        from pathlib import Path
        dotenv = Path(__file__).resolve().parent.parent.parent / ".env"
        if dotenv.exists():
            for line in dotenv.read_text().splitlines():
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    if key:
                        return key
        import os
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise ExtractionError("GEMINI_API_KEY not set (put it in .env)")
        return key

    def _generate(self, prompt: str, image_png: bytes | None = None) -> str:
        parts = [{"text": prompt}]
        if image_png is not None:
            parts.append({"inline_data": {"mime_type": "image/png",
                                          "data": base64.b64encode(image_png).decode()}})
        body = json.dumps({
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.0},
        }).encode()
        req = urllib.request.Request(
            self.API.format(model=config.get().GEMINI_MODEL),
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": self._key})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        return data["candidates"][0]["content"]["parts"][0]["text"]

    # -- PerceptionProvider protocol -------------------------------------------
    def extract_amendments(self, dataset: Dataset, user_id: str) -> tuple:
        # amendments use the same deterministic parsers (they are reliable);
        # the LLM layer is reserved for OCR, where regex cannot work.
        from perception import DeterministicPerception
        return DeterministicPerception().extract_amendments(dataset, user_id)

    def extract_image_amount(self, image_id: str) -> float:
        from pathlib import Path
        path = (Path(__file__).resolve().parent.parent.parent
                / "dataset" / "media" / "images" / f"{image_id}.png")
        if not path.exists():
            raise ExtractionError(f"image file missing for {image_id}")
        text = self._generate(
            "This is a financial document (receipt/bill/payslip). Extract "
            "the total amount billed/paid/net as a number and its currency. "
            'Reply ONLY with JSON: {"amount": <number|null>, "currency": "<code>"}',
            path.read_bytes())
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ExtractionError(f"unparseable OCR response for {image_id}")
        amount = json.loads(m.group(0)).get("amount")
        if amount is None:
            raise ExtractionError(f"no amount found in {image_id}")
        return float(amount)