# 2026-11-08 #18 — Less "thinking" for mechanical calls, junk words fixed at draft time, cost per project

**Request:** stop GPT over-thinking / junk; verbosity medium?; go ahead with recommendation (1, 3, 5); compare on two
new InfoVision projects (Casino, Planet Fitness from D:\HunterAgent\Dataset); cost per project for DevOps.

**Done (commit 04c2c3a):** `core/llm_effort.py` (settings / light / light_call); Azure `_payload` reads it.
light (effort low, verbosity low, cap): extract._classify_batch 4000, entity_relevance._ask 3000, vision.matches /
is_logo_of 1000, count_reading.readings 2000, article_tagging._call + rq_tagging._call (no cap: own budgets).
Defaults unchanged (medium, 16384) for insights/brief/strategy. Live: Azure gpt-5 accepts `verbosity` on
2025-01-01-preview; light call answered with 0 reasoning tokens. insights._guardrail_words: drafts with an
org-prohibited word go to the existing repair round. Tests 26 passed.
**Verbosity:** "medium" is GPT-5's default (no change); low used only for mechanical calls until the A/B.
**Env:** hunter-postgres container had exited after a Docker/Hyper-V hiccup → `docker start hunter-postgres`.

**Cost data (llm_usage, local):** project 1 Casino Gaming measured only Brief→Strategy: $2.24 (brief_scope $1.91 /
52 calls, research $0.17, strategy $0.17). Tagging and deck have no local records → estimated from batch constants and
GPT-5 prices ($1.25/M in, $0.125/M cached, $10/M out).
**Pending:** the two comparison projects (needs article-budget confirmation: memory rule 1000 articles).
