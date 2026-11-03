"""Jev (TypeSafe AI): a non-generative "System One" model that answers typed questions about a piece of text
with calibrated probabilities instead of generated text -- constrained decoding by construction, so an answer is
always one of the given options. https://docs.typesafe.ai

  Choice  pick one of up to 255 named options      -> choice, probabilities, confidence
  Score   rate on an ordered scale of 2-10 levels   -> score (0..top level, weighted), probabilities, confidence
  Noul    probability that a statement holds        -> noul (0..1)

All questions in one request are answered about the same `state`, in parallel, in ~70-500 ms.
Env: TYPESAFE_API_KEY (required to use it), TYPESAFE_MODEL (default jev-latest). Without a key every caller
uses its own deterministic fallback, as Hunter's LLM-backed features do. The key is never logged.
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests

logger = logging.getLogger(__name__)

API_URL = "https://api.typesafe.ai/v1/systemone"
TIMEOUT_S = 30
RETRY_STATUSES = {429, 529}  # rate limited / overloaded: back off and retry, per the API docs
MAX_ATTEMPTS = 4
MAX_STATE_CHARS = 12_000  # a news article's opening carries its subject and tone; bounds cost per call
WORKERS = 8


AUTH_FAILURE_PAUSE_S = 600  # after the key is rejected, Jev is off this long: callers use their previous logic


class JevError(RuntimeError):
    """Jev could not answer (unconfigured, rejected, or still failing after retries)."""


_paused_until = 0.0


def is_configured() -> bool:
    """A key is set and hasn't just been rejected. False sends every caller straight to its previous logic."""
    return bool(os.environ.get("TYPESAFE_API_KEY", "").strip()) and time.monotonic() >= _paused_until


def _pause_after_auth_failure() -> None:
    global _paused_until
    _paused_until = time.monotonic() + AUTH_FAILURE_PAUSE_S
    logger.warning("Jev rejected the API key; using the previous (non-Jev) logic for %ss", AUTH_FAILURE_PAUSE_S)


def choice(instructions: str, options: dict[str, str]) -> dict:
    """A Choice question: `options` maps each option's name to what it means."""
    return {"type": "choice", "instructions": instructions, "criteria": options}


def score(instructions: str, levels: list[str]) -> dict:
    """A Score question: `levels` run from the low end of the scale to the high end (2-10 of them)."""
    return {"type": "score", "instructions": instructions, "criteria": levels}


def noul(instructions: str, true: str | None = None, false: str | None = None) -> dict:
    """A yes/no question; `true`/`false` optionally describe what each answer means."""
    question: dict = {"type": "noul", "instructions": instructions}
    if true or false:
        question["criteria"] = {"true": true, "false": false}
    return question


def _retry_after(r: requests.Response, attempt: int) -> float:
    try:
        return min(float(r.headers.get("Retry-After", "")), 30.0)
    except ValueError:
        return float(2 ** attempt)


def ask(state: str, questions: dict[str, dict]) -> dict[str, dict]:
    """Answers keyed by question id. Raises JevError when Jev can't answer -- callers fall back."""
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key or not is_configured():
        raise JevError("Jev unavailable (no key, or the key was just rejected)")
    body = {"state": (state or "")[:MAX_STATE_CHARS], "questions": questions,
            "model": os.environ.get("TYPESAFE_MODEL", "").strip() or "jev-latest"}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for attempt in range(MAX_ATTEMPTS):
        try:
            r = requests.post(API_URL, json=body, headers=headers, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            if attempt == MAX_ATTEMPTS - 1:
                raise JevError(f"Jev unreachable: {type(e).__name__}") from None
            time.sleep(2 ** attempt)
            continue
        if r.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS - 1:
            time.sleep(_retry_after(r, attempt))
            continue
        if r.status_code in (401, 403):
            _pause_after_auth_failure()
            raise JevError(f"Jev rejected the API key (HTTP {r.status_code})")
        if r.status_code != 200:
            raise JevError(f"Jev returned HTTP {r.status_code}")  # body may echo the request: not logged
        try:
            answers = r.json()["answers"]
        except (ValueError, KeyError, TypeError):
            raise JevError("Jev returned an unreadable response") from None
        if not all(qid in answers for qid in questions):
            raise JevError("Jev left questions unanswered")
        return answers
    raise JevError("Jev still rate-limited after retries")


def ask_many(states: list[str], questions: dict[str, dict]) -> list[dict[str, dict] | None]:
    """The same questions about many texts, concurrently. None for a text Jev couldn't answer."""
    def one(state: str) -> dict[str, dict] | None:
        try:
            return ask(state, questions)
        except JevError as e:
            logger.warning("Jev: %s", e)
            return None

    if not states:
        return []
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(states))) as pool:
        return list(pool.map(one, states))
