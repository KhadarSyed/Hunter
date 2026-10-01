# Hunter Brief-to-Deck Agent

A locally-hosted agent that watches for new client briefs, searches your entire
repository of past Hunter PR project decks for the most relevant slides, drafts
whatever content is missing, and assembles a fresh branded deck - with a chat UI
that shows a live, step-by-step feed of what it's doing, and a memory of every
past run.

The backend (Python/FastAPI) and the UI (React) run on this machine; the language
model calls go to Azure OpenAI (chat) and NVIDIA NIM (embeddings), configured via
`.env`.

## How it works

1. Drop a client brief (`.docx`, `.txt`, or `.pptx`) into the **briefs inbox** folder,
   or paste one directly into the chat.
2. The agent parses it, embeds it, and searches the slide index built from every
   deck in your **repository** folder.
3. The LLM decides which slides are genuinely relevant, groups them into
   sections, and drafts new slides (qualitative framing only - it never invents
   statistics) for anything the brief asks for that no past slide covers.
4. Relevant historical slides are copied into the new deck exactly as they were
   (charts, images, formatting intact - via PowerPoint automation), tagged with
   where they came from. Drafted slides are clearly marked `SOURCE: AGENT DRAFT`.
5. The finished deck is saved to your **output** folder, and every run - the
   brief, what was reused, what was drafted, the whole step-by-step timeline -
   is remembered so you can revisit it later from the History sidebar.

## One-time setup

Already done for you in this environment:
- Node.js installed (via winget)
- Azure OpenAI and NVIDIA NIM API keys configured in `.env` (see `.env.example`)
- Python dependencies installed
- Branding template copied to `agent/data/hunter_template.pptx`
- Folders configured (see `agent/data/settings.json`, editable from the UI too):
  - Repository: `...\Hunter PR\2026\All PPT Decks`
  - Briefs inbox: `...\Hunter PR\2026\New Client Brief Feeder Agent`
  - Output: `...\Hunter PR\2026\Agent Output`

If you ever need to redo this on another machine:

```powershell
winget install -e --id OpenJS.NodeJS.LTS

# Copy .env.example to .env and fill in AZURE_OPENAI_* / NVIDIA_EMBED_* keys

# Backend deps (use your real python.exe - see "Known quirk" below)
<python.exe> -m pip install -r agent/requirements.txt

# Frontend deps
cd web
npm install
```

## Running it

```powershell
.\start.ps1
```

This starts the backend on `http://127.0.0.1:8000`, the frontend on
`http://127.0.0.1:5173`, and opens your browser.

To stop, close the two windows it opens (backend + frontend).

### Running pieces manually

```powershell
# Backend
cd agent
<python.exe> -m uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd web
npm run dev
```

## Known quirk on this machine

Plain `python` / `pip` on PATH resolve to a broken Microsoft Store stub. Always use
the real interpreter directly:

```
C:\Users\sweta.shah\AppData\Local\Python\bin\python3.exe
```

`start.ps1` already accounts for this.

## Performance expectations

Expect:
- First-time repository indexing: a few minutes per ~10 decks (one-time; only
  changed/new decks get re-indexed after that).
- A full run (brief → finished deck): roughly 3-10 minutes depending on how many
  new slides need drafting, since each is a separate reasoning step.

The live feed in the chat UI shows exactly what step it's on so it never looks
stuck.

## Settings

Click **Settings** in the sidebar to change the repository/briefs/output folders,
or ignore patterns (a `Combined_*` pattern is excluded by default - those are
large concatenated decks in the repository, not real per-client projects).

## Current limitations

- Chat can start a new run (paste a brief) and answer general questions, but it
  cannot yet make targeted edits to an already-finished deck (e.g. "swap slide 4
  for a different one") - that would need to re-enter the assembly pipeline
  surgically and is a good next step.
- Client name and project date are guessed from filenames/brief text; the LLM
  sometimes needs a nudge if your brief doesn't state them explicitly.
- Only one run processes at a time (by design, since PowerPoint automation and
  the local model both operate one at a time on this machine).

## Project layout

```
agent/            Python backend (FastAPI, deck assembly, retrieval, memory)
  app/
  data/            hunter_template.pptx, settings.json, memory.db
web/               React + Vite frontend (light mode, InfoVision violet accent)
start.ps1          One-command launcher
```
