"""Data set upload: many export files -> normalised, split traditional/social, deduplicated by link, kept in S3."""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from pathlib import Path

from ...core import config, object_store, store
from ..exclusions import service as exclusions
from ..execution.service import _load_dataset
from . import normalize, repository as repo

logger = logging.getLogger(__name__)
ALLOWED_EXT = (".csv", ".xlsx", ".xls")
MAX_FILE_BYTES = 50 * 1024 * 1024


def _safe_name(name: str) -> str:
    base = re.split(r"[\/]", name or "")[-1]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "upload"


def _read(name: str, data: bytes) -> list[dict]:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.UPLOAD_DIR / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
    try:
        tmp.write_bytes(data)
        return _load_dataset(str(tmp))
    finally:
        tmp.unlink(missing_ok=True)


def _one(project_id: int, name: str, data: bytes, user: str | None, rules=None) -> dict:
    safe = _safe_name(name)
    out = {"file_name": name, "rows_read": 0, "added": 0, "duplicates": 0, "blocked": 0, "error": None}
    fid = None
    try:
        if Path(safe).suffix.lower() not in ALLOWED_EXT:
            out["error"] = "Unsupported file type (use .csv, .xlsx or .xls)"
        elif len(data) > MAX_FILE_BYTES:
            out["error"] = "File is larger than 50 MB"
        elif not data:
            out["error"] = "File is empty"
        key = None if out["error"] else object_store.put_bytes(
            f"datasets/project-{project_id}/{uuid.uuid4().hex[:8]}-{safe}", data)
        fid = repo.add_file(project_id, name, key, None if key or out["error"] else data, user)
        if not out["error"]:
            raw = _read(safe, data)
            recs, out["error"] = normalize.records(raw)
            out["rows_read"] = len(raw)
            if recs:
                unique = list({r["norm_url"]: r for r in reversed(recs)}.values())[::-1]     # first row per link wins
                allowed = [r for r in unique if not (rules and exclusions.blocked_domain(rules, r["url"]))]
                out["blocked"] = len(unique) - len(allowed)     # the org's blocked websites are never stored
                out["added"], out["duplicates"] = repo.insert_articles(project_id, fid, allowed)
                out["duplicates"] += len(recs) - len(unique)
    except Exception as e:                      # one bad file must not stop the others
        logger.warning("Upload of %s failed: %s", safe, e)
        out["error"] = out["error"] or f"Could not process the file: {type(e).__name__}"
    finally:
        if fid is not None:
            try:
                repo.finish_file(fid, out["rows_read"], out["added"], out["duplicates"], out["error"])
            except Exception as e:
                logger.warning("Could not record the result of %s: %s", safe, e)
    return out


def upload(project_id: int, files: list[tuple[str, bytes]], user: str | None) -> dict:
    rules = exclusions.rules_for_project(project_id)
    results = [_one(project_id, name, data, user, rules) for name, data in files]
    try:
        counts = repo.channel_counts(project_id)
    except Exception as e:                      # the per-file results are already saved; do not lose them
        logger.warning("Channel counts failed: %s", e)
        counts = {}
    return {"files": results, "added": sum(r["added"] for r in results),
            "duplicates": sum(r["duplicates"] for r in results), "blocked": sum(r["blocked"] for r in results),
            "traditional": counts.get("traditional", 0), "social": counts.get("social", 0)}


# ---- tagging (the job lives in tagging_job.py) ---------------------------------------------------------------------
from .tagging_job import TaggingBusy, is_tagging, start_tagging, tagging_state  # noqa: E402,F401


# ---- query panel: per-RQ query preview, free re-match, needs-tagging counts and the re-tag estimate -----------------
PREVIEW_TITLES = 50
DROPPED_REASON = "No longer matches the edited query"


NO_TERMS = "No searchable terms in this query"
_OPERATOR = re.compile(r"^(AND|OR|NOT|NEAR(/\d+)?)$", re.IGNORECASE)


_NOT = re.compile(r"\bNOT\b\s*")     # Meltwater operators are upper case; "not" inside a phrase is a word


def _clause_end(query: str, j: int) -> int:
    """End of the term, quoted phrase or whole bracketed group that starts at j."""
    if query[j:j + 1] == "(":
        depth = 0
        for k in range(j, len(query)):
            depth += {"(": 1, ")": -1}.get(query[k], 0)
            if depth == 0:
                return k + 1
        return len(query)
    if query[j:j + 1] == '"':
        k = query.find('"', j + 1)
        return len(query) if k < 0 else k + 1
    m = re.match(r"[^\s()]+", query[j:])
    return j + (m.end() if m else 0)


def _split_not(query: str) -> tuple[str, str]:
    """(the query without its NOT clauses, the NOT clauses' text)."""
    kept, negated, pos = [], [], 0
    for m in _NOT.finditer(query):
        if m.start() < pos or query[:m.start()].count('"') % 2:     # inside a clause already taken, or a phrase
            continue
        end = _clause_end(query, m.end())
        kept.append(query[pos:m.start()])
        negated.append(query[m.end():end])
        pos = end
    kept.append(query[pos:])
    return " ".join(kept), " ".join(negated)


def _plain_terms(text: str) -> list[str]:
    phrases = [p.strip() for p in re.findall(r'"([^"]*)"', text) if p.strip()]
    words = re.split(r"[\s()\[\]]+", re.sub(r'"[^"]*"', " ", text))
    bare = [w.strip("*?") + ("*" if w.endswith("*") else "") for w in words if w and not _OPERATOR.match(w)]
    return phrases + [w for w in bare if w.strip("*")]


def match_terms(query: str) -> list[str]:
    """The terms the free re-match looks for (tagging itself is unchanged): the tagger's bracketed groups, else every
    quoted phrase and every bare word outside the operators and outside NOT clauses (wildcards stripped; a trailing *
    still matches endings)."""
    from ...agents import rq_tagging
    return rq_tagging._terms(query or "") or _plain_terms(_split_not(query or "")[0])


def query_errors(query: str) -> list[str]:
    from ...agents.meltwater_query_builder import validate_boolean_syntax
    return validate_boolean_syntax(query) + ([] if match_terms(query) else [NO_TERMS])


def _matching(query: str, arts: list[dict]) -> set[int]:
    """Articles the Boolean query matches (AND / OR / NOT / NEAR, title:), evaluated in Python. A query that cannot
    be read falls back to "any positive term" and is logged, so an odd query never silently empties a question."""
    from . import boolean
    node = boolean.parse(query)
    if node is not None:
        return {a["id"] for a in arts if boolean.matches(node, a.get("text") or "", a.get("title") or "")}
    from ...agents import question_dimensions as qd
    logger.warning("Boolean query could not be read; matching any of its terms: %s", (query or "")[:120])
    terms = match_terms(query)
    return {a["id"] for a in arts if qd.keyword_hits(a.get("text") or "", terms)}


def match_rqs(project_id: int) -> dict:
    """Map every article to the approved research questions its Boolean query matches (keyword hits, no GPT).
    Articles no question matches go to Irrelevant and are never tagged. A question with no searchable terms
    matches every article (nothing to filter on). Returns matched articles per question and the pool sizes."""
    from ..deliverable import rows
    arts = repo.match_texts(project_id)
    dropped = _drop_blocked_domains(project_id, arts)       # a domain rule added after the upload
    if dropped:
        arts = [a for a in arts if a["id"] not in dropped]
    groups = _syndication_groups(arts)
    repo.save_copies(project_id, {c: g[0] for g in groups for c in g[1:]})
    group_of = {i: g for g in groups for i in g}
    blocked = {**scope_reasons(project_id, arts), **blocked_reasons(project_id, arts)}   # a block wins over scope
    by_rq = {}
    for q in rows.approved_rqs(project_id):
        hits = _matching(q.query, arts) if match_terms(q.query) else {a["id"] for a in arts}
        by_rq[q.id] = {m for i in hits for m in group_of.get(i, (i,))} - blocked.keys()   # a group matches as one story
    repo.save_blocked(project_id, blocked)          # first: frees rows of articles no longer blocked
    repo.save_rq_matches(project_id, by_rq)
    matched = set().union(*by_rq.values()) if by_rq else set()
    out_of_scope = sum(1 for why in blocked.values() if why.startswith(repo.OUT_OF_SCOPE_PREFIX))
    return {"per_rq": {k: len(v) for k, v in by_rq.items()}, "matched": len(matched),
            "irrelevant": len(arts) - len(matched) - len(blocked), "blocked": len(blocked) - out_of_scope,
            "out_of_scope": out_of_scope, "total": len(arts),
            "copies": sum(len(g) - 1 for g in groups), "dropped": len(dropped)}


def _drop_blocked_domains(project_id: int, arts: list[dict]) -> set[int]:
    """Deletes the project's articles from the organization's blocked websites (a rule added after the upload);
    one an analyst kept relevant or decided on stays. Returns the deleted ids. Pure Python, no LLM."""
    rules = exclusions.rules_for_project(project_id)
    if not rules.domains:
        return set()
    ids = [a["id"] for a in arts if not a.get("keep_at") and exclusions.blocked_domain(rules, a.get("url") or "")]
    gone = repo.delete_undecided_articles(project_id, ids)
    if gone:
        logger.info("project %s: %d articles from blocked websites removed", project_id, len(gone))
    return gone


SCOPE_KEY = "data_set_scope"     # in the project's spec: {"country", "from", "to"} chosen on the Data set page


def scope(project_id: int, arts: list[dict] | None = None) -> dict:
    """The Data set scope filter: the analyst's choice, else the uploaded data's own date range and the Brief &
    Scope country (a single scope country, else every country). Dates are ISO days; '' means no bound."""
    project = store.get_project(project_id) or {}
    spec = project.get("spec") or {}
    arts = repo.match_texts(project_id) if arts is None else arts
    days = sorted(d for d in ((a.get("published") or "")[:10] for a in arts) if d)
    countries = (spec.get("included_scope") or {}).get("countries") or []
    saved = spec.get(SCOPE_KEY) or {}
    default = {"country": countries[0] if len(countries) == 1 else "", "from": days[0] if days else "",
               "to": days[-1] if days else ""}
    pick = {k: saved[k] if k in saved else default[k] for k in default}     # a saved '' (every country) wins too
    return {**pick,
            "data_from": days[0] if days else "", "data_to": days[-1] if days else "",
            "countries": sorted({a["country"] for a in arts if a.get("country")})}


def scope_reasons(project_id: int, arts: list[dict]) -> dict[int, str]:
    """{article id: why} for articles outside the scope filter. An article with no date or no country is kept for
    that part (nothing to judge it on); one an analyst kept relevant is never set aside."""
    s = scope(project_id, arts)
    out = {}
    for a in arts:
        if a.get("keep_at"):
            continue
        day, country = (a.get("published") or "")[:10], (a.get("country") or "").strip()
        if day and ((s["from"] and day < s["from"]) or (s["to"] and day > s["to"])):
            out[a["id"]] = f"{repo.OUT_OF_SCOPE_PREFIX}: published {day}, outside {s['from']} to {s['to']}"
        elif country and s["country"] and country.lower() != s["country"].lower():
            out[a["id"]] = f"{repo.OUT_OF_SCOPE_PREFIX}: {country}, the scope is {s['country']}"
    return out


def set_scope(project_id: int, country: str, day_from: str, day_to: str) -> dict:
    """Save the analyst's scope filter in the project's spec and re-run the free match (no model call)."""
    project = store.get_project(project_id) or {}
    spec = {**(project.get("spec") or {}), SCOPE_KEY: {"country": country.strip(), "from": day_from, "to": day_to}}
    store.update_project(project_id, spec=spec)
    return match_rqs(project_id)


def blocked_reasons(project_id: int, arts: list[dict]) -> dict[int, str]:
    """{article id: why} for articles naming a keyword the organization's exclusion list blocks (Settings >
    Exclusions). Blocked websites are dropped, not listed (upload / _drop_blocked_domains); one an analyst kept or
    decided on is checked by keyword only. An article an analyst kept relevant is never blocked again. Blocked
    articles go to Irrelevant and are never tagged until an analyst marks them relevant and runs Re-tag."""
    rules = exclusions.rules_for_project(project_id)
    if not rules.keywords:
        return {}
    by_keyword = exclusions.Rules(keywords=rules.keywords)
    out = {}
    for a in arts:
        if a.get("keep_at"):
            continue
        why = exclusions.excluded(by_keyword, "", a.get("text") or "")
        if why:
            out[a["id"]] = f"{repo.BLOCK_PREFIX} ({why})"
    return out


def keep_relevant(project_id: int, article_id: int, by: str, comment: str) -> dict | None:
    """An analyst keeps a blocked article relevant: the override is stored on the article, the organization remembers
    it (Settings > Exclusions shows it; its AI agents get it as context) and the Boolean match runs again (free)."""
    art = repo.keep_relevant(project_id, article_id, by, comment)
    if art is None:
        return None
    exclusions.remember_override(project_id, art.get("excluded_reason") or "", comment, by, art.get("url") or "")
    return match_rqs(project_id)


def _syndication_groups(arts: list[dict]) -> list[list[int]]:
    """Syndicated copies, found in Python: the same headline once its publisher suffix is cleaned off
    ("Ford bets $1B - Automotive News" and "Ford bets $1B | Reuters"). Groups of 2+, ids ascending (first = original).
    Near-identical text under a new headline is left to the relations phase (embeddings)."""
    from ..research.relations import _title_key
    by_key: dict[str, list[int]] = {}
    for a in arts:
        key = _title_key(a.get("title"))
        if len(key) >= 20:          # a short headline ("Breaking news") is not evidence of the same story
            by_key.setdefault(key, []).append(a["id"])
    return [sorted(ids) for ids in by_key.values() if len(ids) > 1]


def _before_after(project_id: int, rq, edited: str) -> tuple[set[int], set[int], dict[int, str]]:
    """Articles the current query matches (its stored matched rows when it has no searchable terms) and the edited."""
    arts = repo.match_texts(project_id)
    old = _matching(rq.query, arts) if match_terms(rq.query) else set(repo.matched_ids(project_id, rq.id))
    return old, _matching(edited, arts), {a["id"]: a["title"] for a in arts}


def preview(project_id: int, rq, edited: str) -> dict:
    """What the edited query would match against the current one. Reads only; writes nothing."""
    old, new, titles = _before_after(project_id, rq, edited)

    def listed(ids: set[int]) -> list[dict]:
        return [{"id": i, "title": titles.get(i, "")} for i in sorted(ids)[:PREVIEW_TITLES]]
    errors = query_errors(edited)
    return {"valid": not errors, "errors": errors, "current": len(old), "edited": len(new),
            "added": listed(new - old), "dropped": listed(old - new)}


def plan_rematch(project_id: int, rq, edited: str) -> dict:
    """The free re-match (keyword hits, no GPT), computed before the query is saved; apply with apply_rematch."""
    old, new, _ = _before_after(project_id, rq, edited)
    return {"old_signature": rq_signature(rq, rq_schemas(project_id)), "added": sorted(new - old),
            "dropped": sorted(old - new)}


def apply_rematch(project_id: int, rq_id: str, plan: dict) -> None:
    repo.apply_rematch(project_id, rq_id, plan["old_signature"], plan["added"], plan["dropped"], DROPPED_REASON)


def rq_schemas(project_id: int) -> dict:
    from ..strategy import tag_schemas
    return tag_schemas.project_tag_schemas(project_id, None)


def rq_signature(rq, schemas: dict) -> str:
    from ...agents import rq_tagging
    return rq_tagging.signature(rq, schemas.get(rq.id))


def rq_counts(project_id: int, rq, schemas: dict) -> dict:
    return repo.rq_counts(project_id, rq.id, rq_signature(rq, schemas))


def estimate(project_id: int, rq) -> dict:
    """What "Re-tag this question" would send to GPT: the rows needing tagging, packed as the job packs them."""
    from ...agents import rq_tagging
    from ..usage import service as usage
    from . import batching
    from .tagging_job import ALL
    todo = repo.rq_rows_needing(project_id, rq.id, rq_signature(rq, rq_schemas(project_id)), ALL)
    batches = batching.pack(todo, rq_tagging._body, out_per_item=rq_tagging.OUT_PER_ARTICLE)
    inp = sum(batching.tokens(rq_tagging._body(a)) for a in todo)
    out = rq_tagging.OUT_PER_ARTICLE * len(todo)
    cost = usage.cost_usd("azure_openai", os.getenv("AZURE_OPENAI_MODEL", ""), usage.deployment_type("azure_openai"),
                          inp, 0, out, time.time())
    return {"articles": len(todo), "batches": len(batches), "input_tokens": inp, "output_tokens": out,
            "cost_usd": cost}


# ---- learning from analysts: corrections recorded for later tagging (domains/feedback) -----------------------------
def _tag_view(tags_json: str | None) -> dict:
    """{sentiment, themes, brands} of stored article tags (what an analyst can edit)."""
    import json
    t = json.loads(tags_json or "{}")
    themes = t.get("themes") or {}
    return {"sentiment": t.get("overall_sentiment"),
            "themes": [v for v in (themes.get(k) for k in ("primary", "secondary", "tertiary")) if v]
            if isinstance(themes, dict) else [],
            "brands": [b.get("brand") for b in t.get("brands") or [] if isinstance(b, dict) and b.get("brand")]}


def learn_edit(project_id: int, article_id: int, before_tags: str | None, after_tags: str | None,
               comment: str | None, by: str | None) -> None:
    """An analyst's tag edit becomes an example for similar articles (only when something changed)."""
    from ..feedback import service as feedback
    before, after = _tag_view(before_tags), _tag_view(after_tags)
    if before != after or comment:
        feedback.record(project_id, [{"article_id": article_id, "kind": "edit", "before": before, "after": after,
                                      "comment": comment}], by)


def learn_decision(project_id: int, article_ids: list[int], rq_id: str | None, status: str, reason: str | None,
                   was_irrelevant: set[int], by: str | None) -> None:
    """A rejection teaches "not relevant to this question"; approving an Irrelevant article teaches "relevant".
    Approving an article the AI already matched confirms it and is not recorded."""
    from ..deliverable import rows
    from ..feedback import service as feedback
    question = next((q.question for q in rows.approved_rqs(project_id) if q.id == rq_id), None) if rq_id else None
    if status == "irrelevant":
        ids, kind = article_ids, "reject"
    elif status == "approved":
        ids, kind = [i for i in article_ids if i in was_irrelevant], "relevant"
    else:
        return
    feedback.record(project_id, [{"article_id": i, "kind": kind, "rq_id": rq_id, "question": question,
                                  "comment": reason} for i in ids], by)


def learn_keep(project_id: int, article_id: int, comment: str, by: str | None) -> None:
    from ..feedback import service as feedback
    feedback.record(project_id, [{"article_id": article_id, "kind": "keep", "comment": comment}], by)
