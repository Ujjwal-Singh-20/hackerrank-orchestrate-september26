"""perception: LLM/OCR boundary ONLY — message-amendment extraction and image
amount extraction. Everything here sits behind PerceptionProvider so tests can
inject a stub with no network. The default provider is deterministic (cached
OCR values + regex parsers over the generator's message phrasings)."""

from __future__ import annotations
import re
from datetime import date
from pathlib import Path
from typing import Protocol

import config
from errors import ExtractionError
from schemas import Amendment, AmendmentType, Dataset, PerceptionResult

# ---------------------------------------------------------------------------
# Cached image OCR values (extracted with Gemini; see code/ocr_gemini.py and
# docs/GENERALIZATION_POLICY.md — these are dataset facts, not fitted labels).
# event_id -> amount in the event's own currency.
# ---------------------------------------------------------------------------
IMAGE_AMOUNT_CACHE: dict[str, float] = {
    "event_253":  4365000.0,   # image_01 payslip net pay (IDR)
    "event_1442": 100000.0,    # image_02 rent receipt Balance Due (INR) - outstanding rent balance
    "event_1545": 41272.0,     # image_03 grocery cash paid (INR)
    "event_1700": 2854.0,      # image_04 delivery item bill (INR)
    "event_1786": 704.05,      # image_05 utility amount due (INR)
    "event_3051": 1995.0,      # image_06 grocery total (INR)
    "event_3231": 8528.10,     # image_07 restaurant total (INR)
    "event_4535": 15339.0,     # image_08 maintenance total received (INR)
    "event_5170": 723.0,       # image_09 water bill (INR)
    "event_6033": 79679.26,    # image_10 invoice total (INR)
    "event_6859": 3650.0,      # image_11 hospital amount payable (INR)
    "event_7307": 33.50,       # image_12 taxi total (USD)
    "event_7941": 2298.0,      # image_13 order total paid (INR)
    "event_9421": 4543.0,      # image_14 handwritten pharmacy bill (INR)
    "event_9806": 9968.0,      # image_15 flight grand total (INR)
    "event_10521": 393.22,     # image_16 EV charging total (INR)
}

_AMT_PAT = re.compile(r"(?:IDR|INR|ZAR|USD|EUR)\s?([\d,]+(?:\.\d+)?)", re.I)
_DATE_PAT = re.compile(r"(\d{4}-\d{2}-\d{2})")
_RENT_PCT_PAT = re.compile(r"increases monthly rent by\s+(\d+)%", re.I)
_TERMINATION_PAT = re.compile(
    r"contract has ended|no[- ]season income|will not be renewed|"
    r"employment has ended|no .*income.*confirmed", re.I)
_INCOME_HINT = ("salary", "pay", "payroll", "gaji")


class PerceptionProvider(Protocol):
    def extract_amendments(self, dataset: Dataset, user_id: str) -> tuple[Amendment, ...]: ...
    def extract_image_amount(self, image_id: str) -> float: ...


class DeterministicPerception:
    """Regex parsers over the dataset's message phrasings + cached OCR."""

    def extract_amendments(self, dataset: Dataset, user_id: str) -> tuple[Amendment, ...]:
        out: list[Amendment] = []
        for m in dataset.messages:
            if m.user_id != user_id:
                continue
            text = m.text
            if _TERMINATION_PAT.search(text):
                out.append(Amendment(AmendmentType.SALARY_TERMINATION, None, None,
                                     note=m.message_id))
                continue
            if "rent" in text.lower() and "increases" in text.lower():
                mp = _RENT_PCT_PAT.search(text)
                if mp:
                    out.append(Amendment(AmendmentType.RENT_INCREASE_PCT,
                                         float(mp.group(1)), None, note=m.message_id))
                continue
            m_amt = _AMT_PAT.search(text)
            if not m_amt:
                continue
            if any(k in text.lower() for k in _INCOME_HINT):
                m_date = _DATE_PAT.search(text)
                eff = date.fromisoformat(m_date.group(1)) if m_date else None
                out.append(Amendment(
                    AmendmentType.SALARY_AMOUNT,
                    float(m_amt.group(1).replace(",", "")),
                    eff, note=m.message_id))
        return tuple(out)

    def extract_image_amount(self, image_id: str) -> float:
        raise ExtractionError(
            f"image {image_id} has no cached OCR amount; run "
            f"code/ocr_gemini.py to rebuild the cache")


def resolve_blank_amounts(dataset: Dataset, provider: PerceptionProvider) -> dict[str, float]:
    """Fill amounts for blank-amount events from linked images (cached OCR)."""
    amounts: dict[str, float] = {}
    for img in dataset.images:
        if not img.related_event_id:
            continue
        ev = dataset.events.get(img.related_event_id)
        if ev is None or ev.amount is not None:
            continue
        if img.image_id in _CACHE_BY_IMAGE:
            amounts[ev.event_id] = _CACHE_BY_IMAGE[img.image_id]
        else:
            amounts[ev.event_id] = provider.extract_image_amount(img.image_id)
    return amounts


# image_id -> amount mirror of IMAGE_AMOUNT_CACHE (event ids are the keys above)
_CACHE_BY_IMAGE: dict[str, float] = {}
for _img_id, _ev_id in {
    "image_01": "event_253", "image_02": "event_1442", "image_03": "event_1545",
    "image_04": "event_1700", "image_05": "event_1786", "image_06": "event_3051",
    "image_07": "event_3231", "image_08": "event_4535", "image_09": "event_5170",
    "image_10": "event_6033", "image_11": "event_6859", "image_12": "event_7307",
    "image_13": "event_7941", "image_14": "event_9421", "image_15": "event_9806",
    "image_16": "event_10521",
}.items():
    _CACHE_BY_IMAGE[_img_id] = IMAGE_AMOUNT_CACHE[_ev_id]


def get_provider() -> PerceptionProvider:
    if config.get().PERCEPTION_PROVIDER == "gemini":
        from perception.gemini_provider import GeminiPerception
        return GeminiPerception()
    return DeterministicPerception()