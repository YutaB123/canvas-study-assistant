"""Local chat bridge: talk to the study assistant's brain right here.
Maintains conversation history in a temp JSON file so follow-ups work.
Usage: python _chat_demo.py "your message"
"""
import sys, os, json
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import anthropic
from dotenv import dotenv_values
from app.canvas import CanvasClient
from app.db import StudyPageStore
from app.study import StudyService
from app.tools import ToolBox
from app.brain import Brain

HIST = os.path.join(os.environ.get("TEMP", "."), "chat_history.json")

def load():
    try:
        return json.load(open(HIST))
    except Exception:
        return []

def save(h):
    json.dump(h, open(HIST, "w"))

def main():
    msg = sys.argv[1]
    v = dotenv_values(".env")
    canvas = CanvasClient(v["CANVAS_BASE_URL"], v["CANVAS_TOKEN"])
    client = anthropic.Anthropic(api_key=v["ANTHROPIC_API_KEY"])
    pages = StudyPageStore("./data/study.sqlite")
    study = StudyService(canvas=canvas, client=client, model=v.get("ANTHROPIC_MODEL", "claude-opus-4-8"),
                         pages=pages, public_base_url=v.get("PUBLIC_BASE_URL", ""))
    tb = ToolBox(canvas=canvas, reminders=None, study=study)
    brain = Brain(client=client, model=v.get("BRAIN_MODEL", "claude-sonnet-4-6"), toolbox=tb)

    history = load()
    before = pages.recent_ids() if hasattr(pages, "recent_ids") else None
    reply = brain.respond(msg, history=history)
    history.append({"role": "user", "content": msg})
    history.append({"role": "assistant", "content": reply})
    save(history)

    print("ASSISTANT:", reply)

if __name__ == "__main__":
    main()
