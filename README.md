# Study Assistant

Text it from your phone like a friend. It's wired to your UW Canvas account, so
it answers from your real classes, assignments, and due dates — and it can set
reminders (delivered as texts) and turn assignments/readings into flashcards or
practice exams (delivered as a web-page link).

See `plan.md` for the plain-English overview of what it does.

## What's inside

```
app/
  config.py     settings loaded from .env
  canvas.py     talks to UW Canvas (courses, assignments, due dates, details)
  timefmt.py    casual due-date phrasing in Pacific time
  tools.py      the tools Claude can call + how Canvas data is formatted
  brain.py      Claude's casual-friend personality + the tool loop
  reminders.py  schedule texts for later (survives restarts)
  study.py      make flashcards / practice exams as a web page
  sms.py        send/receive texts through Twilio (only your number allowed)
  db.py         small local memory (recent chat + generated study pages)
  main.py       the web app: /sms webhook, /study/{id}, /health
tests/          the test suite
```

## Setup

1. **Install** (Python 3.11+):
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
2. **Configure**: copy `.env.example` to `.env` and fill in your values:
   - `ANTHROPIC_API_KEY` — from console.anthropic.com
   - `CANVAS_TOKEN` — UW Canvas → Account → Settings → New Access Token
   - `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` — your Twilio number
   - `MY_PHONE_NUMBER` — your phone (the only number allowed to use it)
   - `PUBLIC_BASE_URL` — your public URL (tunnel for local, host URL when deployed)

## Run it locally

```
.venv\Scripts\uvicorn app.main:create_app --factory --reload
```

Then expose it to Twilio with a tunnel (so texts can reach your machine):

```
ngrok http 8000
```

Put the tunnel URL into `PUBLIC_BASE_URL` in `.env`, and set your Twilio number's
**Messaging webhook** to `https://<your-tunnel>/sms`. Text the number "what's due
this week?" and you should get a reply.

## Run the tests

```
.venv\Scripts\pytest
```

## Deploy (always-on)

Push to a cloud host (Railway / Render / Fly.io). The `Procfile` already has the
start command. After deploying:

- Set the same environment variables in the host's dashboard.
- Set `PUBLIC_BASE_URL` to the host's URL.
- Point your Twilio number's Messaging webhook at `https://<host>/sms`.

Two notes:

- **Run a single instance.** Reminders are scheduled in-process; multiple copies
  would double-fire them.
- **US SMS registration.** Texting real recipients from a US number needs a
  one-time A2P 10DLC registration in Twilio. A trial number works right away for
  texting your own verified phone while building.
