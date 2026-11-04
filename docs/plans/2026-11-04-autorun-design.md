# Autorun: approve Brief & Scope once, run on its own to Data Sources

## Goal
The user approves Brief & Scope once. Background research and search strategy then run and approve themselves.
The next stop for a person is **Data Sources**: review the RQs, upload datasets, review the tagged articles and approve.
That approval starts the deliverable build.

## Flow
1. Brief & Scope page: one **Approve** button. It approves the spec, calls `POST /projects/{id}/autorun`, and opens
   Background Research.
2. Server chain (`domains/projects/autorun.py`). Each step runs when the previous job finishes, through an `on_done`
   step passed into the existing job function:
   1. Start the background research job.
   2. When it finishes, run `compose_brief` and approve the brief and the research.
   3. Start the search strategy job.
   4. When it finishes, approve the strategy and email **Ready for your datasets**.
3. Background Research and Search Strategy pages show the running job live. Each moves to the next page when its stage
   is approved: `intel_brief_approved` opens Search Strategy, and `intel_strategy_approved` opens Data Sources.
4. Data Sources: review and approval are unchanged. **Approve & build deliverable** starts the deck run and opens
   Deliverables.

## Guards
- The chain approves only when today's checks pass: no research blocking reasons, and no strategy validation issues.
  Otherwise it stops at that stage, leaves it unapproved, and emails **Action needed: <stage>**.
- Only the chain started by Approve approves anything. A manual Regenerate stays a draft that needs approving, as today.
- A server restart stops the chain, as it stops any running job. Re-running the stage from its page continues.

## Code moves
- The bodies of the `/research/start` and `/strategy/generate` endpoints move to the `service.py` of research and of
  strategy, as `start_research_job(...)` and `start_strategy_job(...)`. Each takes an optional `on_done`.
  The endpoints keep their behaviour.

## Emails to the project creator
- **Sent:** Ready for your datasets; Datasets tagged (review and approve); a stage failed or blocked; Deliverable
  ready.
- **Not sent:** Brief & Scope (the user is on the page), and research or strategy approval (they approve themselves).

## Tests
- Chain order: research, then brief approved, then strategy, then strategy approved, then the email.
- A blocking reason stops the chain and sends the Action needed email.
- A manual regenerate stays a draft.
- The email list is the four above.
