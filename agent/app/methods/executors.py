"""Deterministic analytical method executors for the Research Executor.

Every executor here implements `BaseMethodExecutor.execute()` using only
keyword matching, counting, grouping, and text extraction over the records
it is given — no LLM calls, no randomness. Given the same records and
context, an executor always returns the same evidence.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date as date_cls
from datetime import datetime, timedelta

from .base import BaseMethodExecutor
from .registry import register

# ---------------------------------------------------------------------------
# Shared vocabulary and helpers
# ---------------------------------------------------------------------------

_POSITIVE_WORDS = {
    "good", "great", "love", "loved", "loves", "excellent", "best", "happy",
    "positive", "satisfied", "recommend", "recommended", "awesome", "fantastic",
    "wonderful", "perfect", "impressive", "amazing", "delight", "delighted",
    "pleased", "enjoy", "enjoyed", "reliable", "trust", "trusted", "win",
    "winning", "success", "successful", "strong", "innovative", "praise",
}

_NEGATIVE_WORDS = {
    "bad", "poor", "terrible", "hate", "hated", "worst", "complaint",
    "complaints", "issue", "issues", "problem", "problems", "disappointing",
    "disappointed", "awful", "fail", "failed", "failure", "broken",
    "negative", "recall", "recalled", "scandal", "lawsuit", "angry",
    "frustrated", "frustrating", "defect", "defective", "unreliable",
    "waste", "unhappy", "regret", "concern", "concerns", "risk", "risky",
}

_CRISIS_WORDS = {
    "complaint", "complaints", "issue", "issues", "problem", "problems",
    "recall", "recalled", "lawsuit", "scandal", "fail", "failure", "failed",
    "broken", "defect", "defective", "boycott", "outage", "breach",
    "controversy", "backlash", "investigation", "fraud", "crisis",
    "warning", "danger", "dangerous", "unsafe", "violation",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d-%b-%Y",
    "%Y/%m/%d",
)


def _record_text(record: dict) -> str:
    """Combine the textual fields of a record for keyword search/display."""
    parts = [str(record.get("headline") or ""), str(record.get("content") or "")]
    text = " ".join(p for p in parts if p).strip()
    return text


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def _parse_date(value) -> date_cls | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_cls):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text[: len(fmt) + 6], fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _record_platform(record: dict) -> str | None:
    return record.get("platform") or record.get("source")


def _record_source(record: dict) -> str | None:
    return record.get("source") or record.get("platform")


def _to_number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _keyword_variants(concept: str) -> list[str]:
    """Break a search concept into lowercase keyword tokens (len > 2)."""
    return [w for w in _tokenize(concept) if len(w) > 2]


def _top_excerpts(records: list[dict], n: int = 3) -> list[dict]:
    """Return up to n records with the longest non-empty text (stable, deterministic)."""
    candidates = [r for r in records if _record_text(r)]
    candidates.sort(key=lambda r: len(_record_text(r)), reverse=True)
    return candidates[:n]


def _keyword_sentiment(record: dict) -> str:
    tokens = set(_tokenize(_record_text(record)))
    pos = len(tokens & _POSITIVE_WORDS)
    neg = len(tokens & _NEGATIVE_WORDS)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def _sentiment_mix(records: list[dict]) -> tuple[int, int, int]:
    pos = neg = neu = 0
    for r in records:
        label = str(r.get("sentiment", "") or "").strip().lower()
        if label not in ("positive", "negative", "neutral"):
            label = _keyword_sentiment(r)
        if label == "positive":
            pos += 1
        elif label == "negative":
            neg += 1
        else:
            neu += 1
    return pos, neg, neu


# ---------------------------------------------------------------------------
# 1. Theme Clustering
# ---------------------------------------------------------------------------


@register("Theme Clustering")
class ThemeClusteringExecutor(BaseMethodExecutor):
    name = "Theme Clustering"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        records = self.preprocess(records, ["content"]) or self.preprocess(records, ["headline"])
        if not records:
            return []

        concepts = context.get("search_concepts") or []
        keyword_groups: dict[str, list[str]] = {}
        for concept in concepts:
            kws = _keyword_variants(concept)
            if kws:
                keyword_groups[concept] = kws

        if not keyword_groups:
            counter: Counter = Counter()
            for r in records:
                counter.update(set(_tokenize(_record_text(r))))
            common = [w for w, _ in counter.most_common(20) if len(w) > 3]
            keyword_groups = {w.title(): [w] for w in common[:8]}

        theme_matches: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            tokens = set(_tokenize(_record_text(r)))
            for theme, kws in keyword_groups.items():
                if any(kw in tokens for kw in kws):
                    theme_matches[theme].append(r)

        ranked = sorted(theme_matches.items(), key=lambda kv: len(kv[1]), reverse=True)
        total = len(records)
        evidence = []
        for theme, matched in ranked[:10]:
            if not matched:
                continue
            share = len(matched) / total if total else 0
            confidence = "high" if len(matched) >= 5 else ("medium" if len(matched) >= 2 else "low")
            reps = _top_excerpts(matched, 2)
            for rep in reps:
                evidence.append({
                    "evidence_type": "theme",
                    "platform": _record_platform(rep),
                    "source": _record_source(rep),
                    "date": rep.get("date"),
                    "text_excerpt": self._truncate(_record_text(rep)),
                    "metrics": {
                        "theme": theme,
                        "mention_count": len(matched),
                        "share_of_records": round(share, 4),
                    },
                    "confidence": confidence,
                    "rationale": f"{len(matched)} of {total} records ({share:.0%}) reference the theme '{theme}'.",
                })
        return evidence[:15]


# ---------------------------------------------------------------------------
# 2. Conversation Analysis
# ---------------------------------------------------------------------------


@register("Conversation Analysis")
class ConversationAnalysisExecutor(BaseMethodExecutor):
    name = "Conversation Analysis"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        records = self.preprocess(records, ["content"]) or self.preprocess(records, ["headline"])
        if not records:
            return []

        by_source: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            by_source[_record_source(r) or "Unknown"].append(r)

        total = len(records)
        evidence = []
        ranked_sources = sorted(by_source.items(), key=lambda kv: len(kv[1]), reverse=True)
        for source, group in ranked_sources[:6]:
            reps = _top_excerpts(group, 1)
            share = len(group) / total if total else 0
            evidence.append({
                "evidence_type": "conversation_volume",
                "platform": _record_platform(group[0]),
                "source": source,
                "date": reps[0].get("date") if reps else None,
                "text_excerpt": self._truncate(_record_text(reps[0])) if reps else "",
                "metrics": {"record_count": len(group), "share_of_records": round(share, 4)},
                "confidence": "high" if len(group) >= 5 else "medium",
                "rationale": f"{len(group)} of {total} conversations originate from {source}.",
            })

        engagement_records = [
            r for r in records
            if _to_number(r.get("engagement")) > 0 or _to_number(r.get("reach")) > 0
        ]
        engagement_records.sort(
            key=lambda r: (_to_number(r.get("engagement")), _to_number(r.get("reach"))),
            reverse=True,
        )
        for rep in engagement_records[:5]:
            evidence.append({
                "evidence_type": "high_engagement_discussion",
                "platform": _record_platform(rep),
                "source": _record_source(rep),
                "date": rep.get("date"),
                "text_excerpt": self._truncate(_record_text(rep)),
                "metrics": {
                    "engagement": _to_number(rep.get("engagement")),
                    "reach": _to_number(rep.get("reach")),
                },
                "confidence": "high",
                "rationale": "Among the highest-engagement discussions identified in the dataset.",
            })

        return evidence[:15]


# ---------------------------------------------------------------------------
# 3. Sentiment Analysis
# ---------------------------------------------------------------------------


@register("Sentiment Analysis")
class SentimentAnalysisExecutor(BaseMethodExecutor):
    name = "Sentiment Analysis"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        records = self.preprocess(records, ["content"]) or self.preprocess(records, ["headline"])
        if not records:
            return []

        has_sentiment_field = any(r.get("sentiment") for r in records)

        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            label = str(r.get("sentiment", "") or "").strip().lower()
            if label not in ("positive", "negative", "neutral"):
                label = _keyword_sentiment(r)
            buckets[label].append(r)

        total = len(records)
        evidence = []
        for label in ("positive", "negative", "neutral"):
            group = buckets.get(label, [])
            if not group:
                continue
            share = len(group) / total if total else 0
            for rep in _top_excerpts(group, 2):
                evidence.append({
                    "evidence_type": "sentiment_distribution",
                    "platform": _record_platform(rep),
                    "source": _record_source(rep),
                    "date": rep.get("date"),
                    "text_excerpt": self._truncate(_record_text(rep)),
                    "metrics": {
                        "sentiment": label,
                        "count": len(group),
                        "share_of_records": round(share, 4),
                        "source_field": "labelled" if has_sentiment_field else "keyword_inferred",
                    },
                    "confidence": "high" if has_sentiment_field else "medium",
                    "rationale": f"{len(group)} of {total} records ({share:.0%}) classified as {label}.",
                })
        return evidence[:15]


# ---------------------------------------------------------------------------
# 4. Volume Analysis
# ---------------------------------------------------------------------------


@register("Volume Analysis")
class VolumeAnalysisExecutor(BaseMethodExecutor):
    name = "Volume Analysis"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        records = self.preprocess(records, ["date"])
        if not records:
            return []

        dated = [(_parse_date(r.get("date")), r) for r in records]
        dated = [(d, r) for d, r in dated if d]
        if not dated:
            return []

        dated.sort(key=lambda pair: pair[0])
        span_days = (dated[-1][0] - dated[0][0]).days

        if span_days > 120:
            granularity = "month"

            def bucket_fn(d: date_cls) -> str:
                return d.strftime("%Y-%m")
        elif span_days > 21:
            granularity = "week"

            def bucket_fn(d: date_cls) -> str:
                iso = d.isocalendar()
                return f"{iso[0]}-W{iso[1]:02d}"
        else:
            granularity = "day"

            def bucket_fn(d: date_cls) -> str:
                return d.strftime("%Y-%m-%d")

        buckets: dict[str, list[dict]] = defaultdict(list)
        for d, r in dated:
            buckets[bucket_fn(d)].append(r)

        ordered = sorted(buckets.items(), key=lambda kv: kv[0])
        counts = [(k, len(v)) for k, v in ordered]
        if not counts:
            return []

        avg = sum(c for _, c in counts) / len(counts)
        peak_key, peak_count = max(counts, key=lambda kv: kv[1])
        trough_key, trough_count = min(counts, key=lambda kv: kv[1])

        evidence = []
        peak_reps = _top_excerpts(buckets[peak_key], 1)
        evidence.append({
            "evidence_type": "volume_trend",
            "platform": _record_platform(peak_reps[0]) if peak_reps else None,
            "source": _record_source(peak_reps[0]) if peak_reps else None,
            "date": peak_key,
            "text_excerpt": self._truncate(_record_text(peak_reps[0])) if peak_reps else "",
            "metrics": {
                "period": peak_key, "granularity": granularity,
                "record_count": peak_count, "average_per_period": round(avg, 2),
            },
            "confidence": "high" if peak_count >= 3 else "medium",
            "rationale": f"Volume peaked at {peak_count} records in {peak_key} ({granularity}), vs an average of {avg:.1f}.",
        })

        if trough_key != peak_key:
            trough_reps = _top_excerpts(buckets[trough_key], 1)
            evidence.append({
                "evidence_type": "volume_trend",
                "platform": _record_platform(trough_reps[0]) if trough_reps else None,
                "source": _record_source(trough_reps[0]) if trough_reps else None,
                "date": trough_key,
                "text_excerpt": self._truncate(_record_text(trough_reps[0])) if trough_reps else "",
                "metrics": {
                    "period": trough_key, "granularity": granularity,
                    "record_count": trough_count, "average_per_period": round(avg, 2),
                },
                "confidence": "high" if len(counts) >= 3 else "medium",
                "rationale": f"Volume dipped to {trough_count} records in {trough_key} ({granularity}), vs an average of {avg:.1f}.",
            })

        for period, count in ordered[:10]:
            evidence.append({
                "evidence_type": "volume_by_period",
                "platform": None,
                "source": None,
                "date": period,
                "text_excerpt": "",
                "metrics": {"period": period, "granularity": granularity, "record_count": count},
                "confidence": "high",
                "rationale": f"{count} records recorded in {period}.",
            })

        return evidence[:15]


# ---------------------------------------------------------------------------
# 5. Share of Voice
# ---------------------------------------------------------------------------


@register("Share of Voice")
class ShareOfVoiceExecutor(BaseMethodExecutor):
    name = "Share of Voice"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        records = self.preprocess(records, [])
        records = [r for r in records if _record_source(r)]
        if not records:
            return []

        by_source: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            by_source[_record_source(r)].append(r)

        total = len(records)
        ranked = sorted(by_source.items(), key=lambda kv: len(kv[1]), reverse=True)
        evidence = []
        for source, group in ranked[:10]:
            share = len(group) / total if total else 0
            reps = _top_excerpts(group, 1)
            evidence.append({
                "evidence_type": "share_of_voice",
                "platform": _record_platform(group[0]),
                "source": source,
                "date": reps[0].get("date") if reps else None,
                "text_excerpt": self._truncate(_record_text(reps[0])) if reps else "",
                "metrics": {"mentions": len(group), "share_pct": round(share * 100, 2)},
                "confidence": "high" if len(group) >= 5 else "medium",
                "rationale": f"{source} accounts for {share:.1%} of mentions ({len(group)} of {total}).",
            })
        return evidence


# ---------------------------------------------------------------------------
# 6. Audience Segmentation
# ---------------------------------------------------------------------------


@register("Audience Segmentation")
class AudienceSegmentationExecutor(BaseMethodExecutor):
    name = "Audience Segmentation"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        records = self.preprocess(records, ["content"]) or self.preprocess(records, ["headline"])
        if not records:
            return []

        by_author: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            key = r.get("author") or _record_source(r) or "Unknown"
            by_author[key].append(r)

        total = len(records)
        segments = []
        for author, group in by_author.items():
            counter: Counter = Counter()
            for r in group:
                counter.update(set(_tokenize(_record_text(r))))
            top_terms = [w for w, _ in counter.most_common(10) if len(w) > 3][:5]
            segments.append((author, group, top_terms))

        segments.sort(key=lambda item: len(item[1]), reverse=True)

        evidence = []
        for author, group, top_terms in segments[:8]:
            share = len(group) / total if total else 0
            reps = _top_excerpts(group, 1)
            evidence.append({
                "evidence_type": "audience_segment",
                "platform": _record_platform(group[0]),
                "source": _record_source(group[0]),
                "date": reps[0].get("date") if reps else None,
                "text_excerpt": self._truncate(_record_text(reps[0])) if reps else "",
                "metrics": {
                    "segment": author,
                    "record_count": len(group),
                    "share_of_records": round(share, 4),
                    "characteristic_terms": top_terms,
                },
                "confidence": "high" if len(group) >= 5 else "medium",
                "rationale": (
                    f"{author} contributes {len(group)} records ({share:.0%}); "
                    f"commonly discusses: {', '.join(top_terms) if top_terms else 'n/a'}."
                ),
            })
        return evidence[:15]


# ---------------------------------------------------------------------------
# 7. Narrative Evolution
# ---------------------------------------------------------------------------


@register("Narrative Evolution")
class NarrativeEvolutionExecutor(BaseMethodExecutor):
    name = "Narrative Evolution"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        records = self.preprocess(records, ["date"])
        dated = [(_parse_date(r.get("date")), r) for r in records]
        dated = [(d, r) for d, r in dated if d]
        if len(dated) < 4:
            return []

        dated.sort(key=lambda pair: pair[0])
        split = len(dated) // 2
        early = [r for _, r in dated[:split]]
        late = [r for _, r in dated[split:]]

        def word_counts(group: list[dict]) -> Counter:
            c: Counter = Counter()
            for r in group:
                c.update(w for w in _tokenize(_record_text(r)) if len(w) > 3)
            return c

        early_counts = word_counts(early)
        late_counts = word_counts(late)
        early_top = {w for w, _ in early_counts.most_common(15)}
        late_top = {w for w, _ in late_counts.most_common(15)}

        emerging = [w for w in late_counts if w in late_top and w not in early_top]
        fading = [w for w in early_counts if w in early_top and w not in late_top]
        persistent = early_top & late_top

        evidence = []
        for word in sorted(emerging, key=lambda w: late_counts[w], reverse=True)[:5]:
            rep = next((r for r in late if word in _tokenize(_record_text(r))), None)
            evidence.append({
                "evidence_type": "narrative_shift_emerging",
                "platform": _record_platform(rep) if rep else None,
                "source": _record_source(rep) if rep else None,
                "date": rep.get("date") if rep else None,
                "text_excerpt": self._truncate(_record_text(rep)) if rep else "",
                "metrics": {
                    "term": word,
                    "mentions_recent_half": late_counts[word],
                    "mentions_early_half": early_counts.get(word, 0),
                },
                "confidence": "medium",
                "rationale": f"'{word}' appears {late_counts[word]} times in the recent period but was largely absent earlier.",
            })

        for word in sorted(fading, key=lambda w: early_counts[w], reverse=True)[:3]:
            rep = next((r for r in early if word in _tokenize(_record_text(r))), None)
            evidence.append({
                "evidence_type": "narrative_shift_fading",
                "platform": _record_platform(rep) if rep else None,
                "source": _record_source(rep) if rep else None,
                "date": rep.get("date") if rep else None,
                "text_excerpt": self._truncate(_record_text(rep)) if rep else "",
                "metrics": {
                    "term": word,
                    "mentions_early_half": early_counts[word],
                    "mentions_recent_half": late_counts.get(word, 0),
                },
                "confidence": "medium",
                "rationale": f"'{word}' was prominent early ({early_counts[word]} mentions) but has faded in recent discussion.",
            })

        if persistent:
            evidence.append({
                "evidence_type": "narrative_persistent_theme",
                "platform": None,
                "source": None,
                "date": None,
                "text_excerpt": "",
                "metrics": {"terms": sorted(persistent)[:8]},
                "confidence": "high",
                "rationale": "These terms remain consistently prominent across both the early and recent periods.",
            })

        return evidence[:15]


# ---------------------------------------------------------------------------
# 8. Crisis Detection
# ---------------------------------------------------------------------------


@register("Crisis Detection")
class CrisisDetectionExecutor(BaseMethodExecutor):
    name = "Crisis Detection"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        records = self.preprocess(records, ["content"]) or self.preprocess(records, ["headline"])
        if not records:
            return []

        flagged: list[tuple[dict, set]] = []
        for r in records:
            tokens = set(_tokenize(_record_text(r)))
            hits = tokens & _CRISIS_WORDS
            is_negative = str(r.get("sentiment", "") or "").strip().lower() == "negative"
            if hits or is_negative:
                flagged.append((r, hits))

        if not flagged:
            return []

        total = len(records)
        flagged.sort(key=lambda pair: len(pair[1]), reverse=True)
        share = len(flagged) / total if total else 0

        top_terms: Counter = Counter()
        for _, hits in flagged:
            top_terms.update(hits)

        evidence = [{
            "evidence_type": "crisis_signal_summary",
            "platform": None,
            "source": None,
            "date": None,
            "text_excerpt": "",
            "metrics": {
                "flagged_record_count": len(flagged),
                "share_of_records": round(share, 4),
                "top_crisis_terms": [w for w, _ in top_terms.most_common(5)],
            },
            "confidence": "high" if share > 0.15 else "medium",
            "rationale": f"{len(flagged)} of {total} records ({share:.0%}) contain crisis-related language or negative sentiment.",
        }]

        for r, hits in flagged[:8]:
            evidence.append({
                "evidence_type": "crisis_mention",
                "platform": _record_platform(r),
                "source": _record_source(r),
                "date": r.get("date"),
                "text_excerpt": self._truncate(_record_text(r)),
                "metrics": {"matched_terms": sorted(hits), "sentiment": r.get("sentiment")},
                "confidence": "high" if hits else "medium",
                "rationale": (
                    f"Contains crisis-related terms: {', '.join(sorted(hits))}."
                    if hits else "Flagged due to negative sentiment."
                ),
            })

        dated_flagged = [(_parse_date(r.get("date")), r) for r, _ in flagged]
        dated_flagged = [(d, r) for d, r in dated_flagged if d]
        if dated_flagged:
            by_day: Counter = Counter(d.isoformat() for d, _ in dated_flagged)
            peak_day, peak_count = by_day.most_common(1)[0]
            if peak_count >= 2:
                evidence.append({
                    "evidence_type": "crisis_spike",
                    "platform": None,
                    "source": None,
                    "date": peak_day,
                    "text_excerpt": "",
                    "metrics": {"date": peak_day, "flagged_count": peak_count},
                    "confidence": "medium",
                    "rationale": f"Crisis-related mentions spiked to {peak_count} on {peak_day}.",
                })

        return evidence[:15]


# ---------------------------------------------------------------------------
# 9. Influencer Identification
# ---------------------------------------------------------------------------


@register("Influencer Identification")
class InfluencerIdentificationExecutor(BaseMethodExecutor):
    name = "Influencer Identification"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        candidates = [
            r for r in records
            if r.get("author") and (_to_number(r.get("reach")) > 0 or _to_number(r.get("engagement")) > 0)
        ]
        if not candidates:
            return []

        by_author: dict[str, list[dict]] = defaultdict(list)
        for r in candidates:
            by_author[r["author"]].append(r)

        ranked = []
        for author, group in by_author.items():
            total_reach = sum(_to_number(r.get("reach")) for r in group)
            total_engagement = sum(_to_number(r.get("engagement")) for r in group)
            ranked.append((author, group, total_reach, total_engagement))

        ranked.sort(key=lambda item: (item[2] + item[3], len(item[1])), reverse=True)

        evidence = []
        for author, group, total_reach, total_engagement in ranked[:10]:
            reps = _top_excerpts(group, 1)
            evidence.append({
                "evidence_type": "influencer",
                "platform": _record_platform(group[0]),
                "source": _record_source(group[0]),
                "date": reps[0].get("date") if reps else None,
                "text_excerpt": self._truncate(_record_text(reps[0])) if reps else "",
                "metrics": {
                    "author": author,
                    "record_count": len(group),
                    "total_reach": total_reach,
                    "total_engagement": total_engagement,
                },
                "confidence": "high" if (total_reach + total_engagement) > 0 else "low",
                "rationale": (
                    f"{author} drove {total_reach:.0f} total reach and {total_engagement:.0f} "
                    f"engagement across {len(group)} record(s)."
                ),
            })
        return evidence


# ---------------------------------------------------------------------------
# 10. Competitive Benchmarking
# ---------------------------------------------------------------------------


@register("Competitive Benchmarking")
class CompetitiveBenchmarkingExecutor(BaseMethodExecutor):
    name = "Competitive Benchmarking"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        records = self.preprocess(records, ["content"]) or self.preprocess(records, ["headline"])
        if not records:
            return []

        brand = (context.get("brand_name") or "").strip()
        concepts = context.get("search_concepts") or []
        competitor_terms = [c for c in concepts if c and c.strip().lower() != brand.lower()]
        if not competitor_terms:
            return []

        brand_tokens = set(_tokenize(brand)) if brand else set()

        groups: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            tokens = set(_tokenize(_record_text(r)))
            for competitor in competitor_terms:
                comp_tokens = set(_keyword_variants(competitor))
                if comp_tokens and comp_tokens & tokens:
                    groups[competitor].append(r)

        brand_group = [r for r in records if brand_tokens and brand_tokens & set(_tokenize(_record_text(r)))]

        total = len(records)
        evidence = []

        if brand_group:
            pos, neg, neu = _sentiment_mix(brand_group)
            reps = _top_excerpts(brand_group, 1)
            evidence.append({
                "evidence_type": "competitive_benchmark",
                "platform": _record_platform(brand_group[0]),
                "source": _record_source(brand_group[0]),
                "date": reps[0].get("date") if reps else None,
                "text_excerpt": self._truncate(_record_text(reps[0])) if reps else "",
                "metrics": {
                    "entity": brand or "brand",
                    "mentions": len(brand_group),
                    "share_of_records": round(len(brand_group) / total, 4) if total else 0,
                    "positive": pos, "negative": neg, "neutral": neu,
                },
                "confidence": "high" if len(brand_group) >= 5 else "medium",
                "rationale": (
                    f"{brand or 'Brand'} mentioned in {len(brand_group)} of {total} records "
                    f"with {pos} positive / {neg} negative signals."
                ),
            })

        ranked_competitors = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
        for competitor, group in ranked_competitors[:8]:
            if not group:
                continue
            pos, neg, neu = _sentiment_mix(group)
            reps = _top_excerpts(group, 1)
            evidence.append({
                "evidence_type": "competitive_benchmark",
                "platform": _record_platform(group[0]),
                "source": _record_source(group[0]),
                "date": reps[0].get("date") if reps else None,
                "text_excerpt": self._truncate(_record_text(reps[0])) if reps else "",
                "metrics": {
                    "entity": competitor,
                    "mentions": len(group),
                    "share_of_records": round(len(group) / total, 4) if total else 0,
                    "positive": pos, "negative": neg, "neutral": neu,
                },
                "confidence": "high" if len(group) >= 5 else "medium",
                "rationale": (
                    f"{competitor} mentioned in {len(group)} of {total} records "
                    f"with {pos} positive / {neg} negative signals."
                ),
            })

        return evidence[:15]


# ---------------------------------------------------------------------------
# 11. Media Framing
# ---------------------------------------------------------------------------


@register("Media Framing")
class MediaFramingExecutor(BaseMethodExecutor):
    name = "Media Framing"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        records = self.preprocess(records, ["headline"])
        if not records:
            return []

        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            tokens = set(_tokenize(r.get("headline", "")))
            pos, neg = len(tokens & _POSITIVE_WORDS), len(tokens & _NEGATIVE_WORDS)
            frame = "positive" if pos > neg else "negative" if neg > pos else "neutral"
            buckets[frame].append(r)

        total = len(records)
        topic_counter: Counter = Counter()
        for r in records:
            topic_counter.update(w for w in _tokenize(r.get("headline", "")) if len(w) > 4)

        evidence = []
        for frame in ("positive", "negative", "neutral"):
            group = buckets.get(frame, [])
            if not group:
                continue
            share = len(group) / total if total else 0
            for rep in _top_excerpts(group, 2):
                evidence.append({
                    "evidence_type": "media_framing",
                    "platform": _record_platform(rep),
                    "source": _record_source(rep),
                    "date": rep.get("date"),
                    "text_excerpt": self._truncate(rep.get("headline", "")),
                    "metrics": {
                        "frame": frame,
                        "headline_count": len(group),
                        "share_of_headlines": round(share, 4),
                    },
                    "confidence": "high" if len(group) >= 5 else "medium",
                    "rationale": f"{len(group)} of {total} headlines ({share:.0%}) carry a {frame} frame.",
                })

        top_topics = [w for w, _ in topic_counter.most_common(5)]
        if top_topics:
            evidence.append({
                "evidence_type": "media_framing_topics",
                "platform": None,
                "source": None,
                "date": None,
                "text_excerpt": "",
                "metrics": {"emphasized_topics": top_topics},
                "confidence": "medium",
                "rationale": f"Headlines most frequently emphasize: {', '.join(top_topics)}.",
            })

        return evidence[:15]


# ---------------------------------------------------------------------------
# 12. Emerging Topics
# ---------------------------------------------------------------------------


@register("Emerging Topics")
class EmergingTopicsExecutor(BaseMethodExecutor):
    name = "Emerging Topics"

    def execute(self, records: list[dict], context: dict) -> list[dict]:
        records = self.preprocess(records, ["date"])
        dated = [(_parse_date(r.get("date")), r) for r in records]
        dated = [(d, r) for d, r in dated if d]
        if len(dated) < 4:
            return []

        dated.sort(key=lambda pair: pair[0])
        latest_date = dated[-1][0]
        cutoff = latest_date - timedelta(days=30)

        recent = [r for d, r in dated if d >= cutoff]
        older = [r for d, r in dated if d < cutoff]

        if len(recent) < max(2, len(dated) // 10) or not older:
            split = max(1, int(len(dated) * 0.75))
            older = [r for _, r in dated[:split]]
            recent = [r for _, r in dated[split:]]

        if not recent or not older:
            return []

        def word_counts(group: list[dict]) -> Counter:
            c: Counter = Counter()
            for r in group:
                c.update(w for w in _tokenize(_record_text(r)) if len(w) > 3)
            return c

        recent_counts = word_counts(recent)
        older_counts = word_counts(older)
        older_vocab = set(older_counts)

        emerging = [(w, c) for w, c in recent_counts.items() if w not in older_vocab and c >= 2]
        emerging.sort(key=lambda item: item[1], reverse=True)

        evidence = []
        for word, count in emerging[:10]:
            rep = next((r for r in recent if word in _tokenize(_record_text(r))), None)
            evidence.append({
                "evidence_type": "emerging_topic",
                "platform": _record_platform(rep) if rep else None,
                "source": _record_source(rep) if rep else None,
                "date": rep.get("date") if rep else None,
                "text_excerpt": self._truncate(_record_text(rep)) if rep else "",
                "metrics": {
                    "term": word,
                    "recent_mentions": count,
                    "older_mentions": older_counts.get(word, 0),
                },
                "confidence": "high" if count >= 4 else "medium",
                "rationale": f"'{word}' was mentioned {count} times recently with no presence in the earlier period.",
            })

        if not evidence:
            growth = []
            for w, c in recent_counts.items():
                prev = older_counts.get(w, 0)
                if prev and c > prev:
                    growth.append((w, c, prev))
            growth.sort(key=lambda item: item[1] - item[2], reverse=True)
            for word, count, prev in growth[:5]:
                rep = next((r for r in recent if word in _tokenize(_record_text(r))), None)
                evidence.append({
                    "evidence_type": "emerging_topic_growth",
                    "platform": _record_platform(rep) if rep else None,
                    "source": _record_source(rep) if rep else None,
                    "date": rep.get("date") if rep else None,
                    "text_excerpt": self._truncate(_record_text(rep)) if rep else "",
                    "metrics": {"term": word, "recent_mentions": count, "older_mentions": prev},
                    "confidence": "medium",
                    "rationale": f"'{word}' grew from {prev} to {count} mentions in the recent period.",
                })

        return evidence[:15]
