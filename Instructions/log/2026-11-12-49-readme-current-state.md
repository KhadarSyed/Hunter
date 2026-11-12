# 2026-11-12-49 Instructions/README "Current state" rewritten for today

**Request:** "continue" (docs checked against the code).

**Found:** the section (dated 2026-11-08) described organisations, projects, test accounts and test models from the
old databases, listed test failures fixed in log 30, and named test providers no longer used.

**Changed:** replaced with the state checked today: production down / local only; local stack and Alembic revision
0001; local data (organisations 1-3, 0 projects, Test Organization's three NVIDIA models in failover order); S3
storage; the last full check results; what is not verified; open questions for the user.

**Verified:** organisations, users, providers, project count and `alembic_version` read from the local database in
this response; other facts from logs 27-48 of this session. Only that section changed (git diff).
