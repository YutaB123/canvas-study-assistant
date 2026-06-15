"""The web app: receives your texts and replies.

`build_app(deps)` makes a FastAPI app from injected services (easy to test).
`create_app()` wires the real services from settings (used to run the server):

    uvicorn app.main:create_app --factory
"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import BackgroundTasks, Body, FastAPI, Form, Header, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

STATIC_DIR = Path(__file__).parent / "static"

# Pick a sensible file extension from a WhatsApp media content-type.
_EXT_BY_TYPE = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
    "application/pdf": ".pdf", "text/plain": ".txt", "text/csv": ".csv",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "video/mp4": ".mp4", "application/zip": ".zip",
}


@dataclass
class AppDeps:
    sms: Any                 # SmsClient-like: is_allowed(), send(), download_media()
    brain: Any               # Brain-like: respond(text, history)
    conversation: Any        # ConversationStore
    study: Any               # StudyPageStore
    require_signature: bool
    validate: Callable[[str, dict, str], bool]
    public_sms_url: str = ""  # the public URL Twilio signs against
    public_base_url: str = ""  # this app's public root (for /file links)
    on_started: Callable[[], None] | None = None
    reminders: Any = None     # ReminderService (for the CLEAR command)
    onedrive: Any = None      # OneDriveClient (file bridge to the laptop folder)
    files: Any = None         # FileStore (serves outbound files to Twilio)
    webchat: Any = None       # WebChatStore (the web app's visible transcript)
    web_chat_secret: str = "" # passcode gating the web chat app
    push: Any = None          # PushService (browser notifications when app is closed)
    vapid_public_key: str = ""# the public key the browser subscribes with


def _filename_for(content_type: str, index: int = 0) -> str:
    ext = _EXT_BY_TYPE.get((content_type or "").split(";")[0].strip().lower(), "")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    return f"{stamp}{f'-{index + 1}' if index else ''}{ext}"


def _handle_media(deps: AppDeps, media: list) -> None:
    """A file came in over WhatsApp — save it to the OneDrive folder."""
    if deps.onedrive is None:
        deps.sms.send("file sharing isn't set up yet.")
        return
    saved = []
    for i, (url, ctype) in enumerate(media):
        try:
            data, real_ctype = deps.sms.download_media(url)
            name = _filename_for(real_ctype or ctype, i)
            deps.onedrive.upload(name, data, real_ctype or ctype)
            saved.append(name)
        except Exception:
            pass
    if saved:
        deps.sms.send(
            f"saved {', '.join(saved)} to your OneDrive '{deps.onedrive.folder}' folder ✅ "
            "(it'll show up on your laptop once OneDrive syncs)"
        )
    else:
        deps.sms.send("hmm, couldn't save that file — mind trying again?")


def _handle_command(deps: AppDeps, body: str) -> bool:
    """If the message is a command, handle it (and send any reply). Returns True
    when handled, False when it should fall through to the brain."""
    cmd = " ".join(body.strip().lower().split())  # normalized

    if cmd in ("clear", "clear chat"):
        deps.conversation.clear()
        deps.sms.send(
            "cleared the chat — i've forgotten our conversation. (heads up: i can "
            "only reset my own memory; i can't delete the messages from your whatsapp.)"
        )
        return True
    if cmd in ("clear reminders", "clear all reminders"):
        n = deps.reminders.clear_all() if deps.reminders is not None else 0
        deps.sms.send(f"cleared your reminders — {n} cancelled.")
        return True
    if cmd in ("clear all", "clear everything", "reset"):
        deps.conversation.clear()
        deps.study.clear()
        if deps.reminders is not None:
            deps.reminders.clear_all()
        deps.sms.send("cleared everything — chat, reminders, and study pages. fresh start ✨")
        return True

    if cmd in ("files", "list files", "list", "my files") and deps.onedrive is not None:
        names = [f["name"] for f in deps.onedrive.list_files()]
        deps.sms.send(
            "your folder's empty — send me a file, or drop one in the OneDrive "
            f"'{deps.onedrive.folder}' folder on your laptop."
            if not names else "files: " + ", ".join(names)
        )
        return True

    if (cmd.startswith("send ") or cmd.startswith("get ")) and deps.onedrive is not None:
        query = body.strip().split(None, 1)[1].strip()
        got = deps.onedrive.download(query)
        if got:
            data, ctype, real_name = got
            fid = uuid.uuid4().hex
            deps.files.save(fid, real_name, ctype, data)
            deps.sms.send(
                f"here's {real_name}:", media_url=[f"{deps.public_base_url}/file/{fid}"]
            )
            return True
        # Only claim it as a file request if it looks like a filename; otherwise
        # let the brain answer things like "get me my grade".
        if re.search(r"\.\w{1,5}$", query):
            deps.sms.send(
                f"couldn't find '{query}' in your folder. text 'files' to see what's there."
            )
            return True
        return False

    return False


TYPING_REFRESH_SECONDS = 20  # each WhatsApp indicator lasts ~25s, so refresh before then


def _keep_typing(deps: AppDeps, message_sid: str, stop: threading.Event) -> None:
    """Keep the WhatsApp 'typing…' animation up until `stop` is set.

    Refreshes every ~20s since each indicator only lasts ~25s. If the native
    indicator isn't available (e.g. the sandbox), fall back to one quick text
    so a slow reply never looks like nothing's happening."""
    if not deps.sms.send_typing(message_sid):
        deps.sms.send("on it 🤔")
        return
    while not stop.wait(TYPING_REFRESH_SECONDS):
        if not deps.sms.send_typing(message_sid):
            return


def _process_incoming(
    deps: AppDeps, body: str, media: list | None = None, message_sid: str = ""
) -> None:
    """The real work, run in the background after we've ack'd Twilio."""
    # Show a 'typing…' animation while we dig, so a slow reply doesn't look dead.
    stop = threading.Event()
    typer = None
    if message_sid and getattr(deps.sms, "channel", "") == "whatsapp":
        typer = threading.Thread(
            target=_keep_typing, args=(deps, message_sid, stop), daemon=True
        )
        typer.start()

    try:
        if media:
            _handle_media(deps, media)
            return
        if _handle_command(deps, body):
            return

        history = deps.conversation.recent()
        reply = deps.brain.respond(body, history=history)
        deps.conversation.save("user", body)
        deps.conversation.save("assistant", reply)
        deps.sms.send(reply)
    finally:
        stop.set()
        if typer is not None:
            typer.join(timeout=2)


class ChatIn(BaseModel):
    text: str = ""


def _web_authed(deps: AppDeps, key: str) -> bool:
    """The web chat is gated by a shared passcode (not a phone whitelist)."""
    return bool(deps.web_chat_secret) and key == deps.web_chat_secret


_CLEAR_CMDS = {"clear", "clear chat", "clear all", "clear everything", "reset"}

GREETING = (
    "hey 👋 i'm your study assistant. ask me what's due, your grades, the syllabus — "
    "anything canvas — or i can whip up a study guide or essay for you."
)


def _ensure_greeting(deps: AppDeps) -> None:
    """Seed a hello so a fresh/empty chat greets you first."""
    if deps.webchat is not None and deps.webchat.max_id() == 0:
        deps.webchat.append("assistant", GREETING)


def build_app(deps: AppDeps) -> FastAPI:
    app = FastAPI(title="Study Assistant")

    if deps.on_started is not None:
        @app.on_event("startup")
        def _startup():
            deps.on_started()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/sms")
    async def sms_webhook(
        background: BackgroundTasks,
        request: Request,
        Body: str = Form(""),
        From: str = Form(""),
    ):
        form = dict((await request.form()))

        # 1. Make sure it's really Twilio (not a faker).
        if deps.require_signature:
            signature = request.headers.get("X-Twilio-Signature", "")
            url = deps.public_sms_url or str(request.url)
            if not deps.validate(url, form, signature):
                return PlainTextResponse("forbidden", status_code=403)

        # 2. Only answer my own number; ignore everyone else.
        if not deps.sms.is_allowed(From):
            return Response(content="", media_type="application/xml")

        # 3. Pull any attached files (WhatsApp media).
        media = []
        try:
            num_media = int(form.get("NumMedia", "0") or 0)
        except ValueError:
            num_media = 0
        for i in range(num_media):
            murl = form.get(f"MediaUrl{i}")
            if murl:
                mtype = form.get(f"MediaContentType{i}", "application/octet-stream")
                media.append((murl, mtype))

        # 4. Ack instantly; do the slow work in the background. Pass the inbound
        #    message SID so we can show a WhatsApp 'typing…' indicator while we work.
        message_sid = (
            form.get("MessageSid") or form.get("SmsMessageSid") or form.get("SmsSid") or ""
        )
        background.add_task(_process_incoming, deps, Body, media, message_sid)
        return Response(content="", media_type="application/xml")

    @app.api_route("/voice", methods=["GET", "POST"])
    def voice():
        # Temporary helper: when a call comes in (e.g. Meta's WhatsApp verification
        # call), answer and record + transcribe it so we can read the spoken code.
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            "<Pause length=\"1\"/>"
            "<Record maxLength=\"40\" playBeep=\"false\" transcribe=\"true\" timeout=\"30\"/>"
            "</Response>"
        )
        return Response(content=twiml, media_type="text/xml")

    @app.get("/study/{page_id}", response_class=HTMLResponse)
    def study_page(page_id: str):
        html = deps.study.get(page_id)
        if html is None:
            return HTMLResponse("Not found", status_code=404)
        return HTMLResponse(html)

    @app.get("/file/{file_id}")
    def serve_file(file_id: str):
        rec = deps.files.get(file_id) if deps.files is not None else None
        if rec is None:
            return Response(content="Not found", status_code=404)
        filename, ctype, data = rec
        return Response(
            content=data,
            media_type=ctype,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    # ---- Web chat app (your own private "texting" interface) ----------------

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/chat")
    def chat_page():
        return FileResponse(STATIC_DIR / "chat.html", media_type="text/html")

    @app.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(
            STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json"
        )

    @app.get("/sw.js")
    def service_worker():
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )

    @app.get("/chat/config")
    def chat_config(x_chat_key: str = Header(default="")):
        if not _web_authed(deps, x_chat_key):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        push_on = deps.push is not None and getattr(deps.push, "enabled", False)
        return {"vapidPublicKey": deps.vapid_public_key if push_on else ""}

    @app.post("/chat/subscribe")
    def chat_subscribe(sub: dict = Body(...), x_chat_key: str = Header(default="")):
        if not _web_authed(deps, x_chat_key):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if deps.push is not None and sub.get("endpoint"):
            deps.push.store.save(sub)
            # Immediately confirm with a real notification (shown even if focused).
            deps.push.notify(
                "Study Assistant", "🔔 Notifications are on — you're all set.", force=True
            )
        return {"ok": True}

    @app.get("/chat/pushdebug")
    def push_debug(x_chat_key: str = Header(default="")):
        if not _web_authed(deps, x_chat_key):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        subs = deps.push.store.all() if deps.push is not None else []
        return {
            "subscriptions": len(subs),
            "enabled": bool(deps.push is not None and getattr(deps.push, "enabled", False)),
            "vapid_tail": (deps.vapid_public_key or "")[-10:],
            "endpoints": [(s.get("endpoint", "") or "")[-18:] for s in subs],
        }

    @app.post("/chat/testpush")
    def test_push(x_chat_key: str = Header(default="")):
        if not _web_authed(deps, x_chat_key):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if deps.push is None:
            return {"results": [{"error": "no push service"}]}
        return {"results": deps.push.send_sync("Study Assistant", "✅ test notification", force=True)}

    @app.get("/chat/messages")
    def chat_messages(after: int = 0, x_chat_key: str = Header(default="")):
        if not _web_authed(deps, x_chat_key):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if after == 0:
            _ensure_greeting(deps)  # first open of a fresh chat → say hello
        return {"messages": deps.webchat.since(after)}

    @app.post("/chat/send")
    def chat_send(payload: ChatIn, x_chat_key: str = Header(default="")):
        if not _web_authed(deps, x_chat_key):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        text = (payload.text or "").strip()
        if not text:
            return {"messages": []}
        norm = " ".join(text.lower().split())
        # Clear wipes EVERYTHING in the chat — the visible transcript and the
        # brain's memory — leaving a truly empty chat (no leftover bubbles).
        if norm in _CLEAR_CMDS:
            deps.webchat.clear()
            deps.conversation.clear()
            if norm in ("clear all", "clear everything", "reset"):
                if deps.reminders is not None:
                    deps.reminders.clear_all()
                if deps.study is not None:
                    deps.study.clear()
            _ensure_greeting(deps)  # a fresh chat greets you again
            return {"messages": deps.webchat.since(0), "cleared": True}
        start = deps.webchat.max_id()
        deps.webchat.append("user", text)
        # Reuse the same pipeline as the phone channels; WebClient.send() writes
        # the brain's reply (and any document links / reminders) into the transcript.
        _process_incoming(deps, text)
        return {"messages": deps.webchat.since(start)}

    return app


def create_app() -> FastAPI:
    """Wire the real services from settings and return the app."""
    from app.config import load_settings
    from app.canvas import CanvasClient
    from app.sms import SmsClient
    from app.tools import ToolBox
    from app.brain import Brain
    from app.db import (
        ConversationStore,
        StudyPageStore,
        FileStore,
        WebChatStore,
        PushStore,
    )
    from app.reminders import ReminderService
    from app.study import StudyService
    from app.onedrive import OneDriveClient
    from app.documents import DocumentService
    from app.webchat import WebClient
    from app.push import PushService

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    import anthropic

    settings = load_settings(require_secrets=True)

    canvas = CanvasClient(settings.canvas_base_url, settings.canvas_token)
    conversation = ConversationStore(settings.data_dir / "conversation.sqlite")
    study_store = StudyPageStore(settings.data_dir / "study.sqlite")
    file_store = FileStore(settings.data_dir / "files.sqlite")
    webchat_store = WebChatStore(settings.data_dir / "webchat.sqlite")
    push_store = PushStore(settings.data_dir / "push.sqlite")
    push_service = PushService(
        push_store, settings.vapid_private_key, settings.vapid_claim_email
    )

    # The channel client the brain/documents/reminders push messages through.
    # "web" routes everything into the web chat transcript; otherwise it's Twilio.
    if settings.channel == "web":
        sms = WebClient(webchat_store, push=push_service)
    else:
        sms = SmsClient(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_from_number,
            my_number=settings.my_phone_number,
            channel=settings.channel,
            whatsapp_from=settings.whatsapp_from,
        )

    onedrive = None
    if settings.onedrive_refresh_token:
        onedrive = OneDriveClient(
            client_id=settings.onedrive_client_id,
            refresh_token=settings.onedrive_refresh_token,
            tenant=settings.onedrive_tenant,
            folder=settings.onedrive_folder,
            token_path=str(settings.data_dir / "onedrive_token.txt"),
        )

    # Persistent scheduler so reminders survive restarts.
    jobs_path = settings.data_dir / "reminders.sqlite"
    scheduler = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{jobs_path}")},
        timezone="UTC",
    )
    reminders = ReminderService(scheduler=scheduler, sms=sms)

    anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    study = StudyService(
        canvas=canvas,
        client=anthropic_client,
        model=settings.anthropic_model,
        pages=study_store,
        public_base_url=settings.public_base_url,
    )

    documents = DocumentService(
        sms=sms,
        files=file_store,
        public_base_url=settings.public_base_url,
        onedrive=onedrive,
    )
    toolbox = ToolBox(canvas=canvas, reminders=reminders, study=study, documents=documents)
    brain = Brain(
        client=anthropic_client,
        model=settings.brain_model,
        toolbox=toolbox,
    )

    deps = AppDeps(
        sms=sms,
        brain=brain,
        conversation=conversation,
        study=study_store,
        require_signature=True,
        validate=sms.validate_signature,
        public_sms_url=f"{settings.public_base_url}/sms",
        public_base_url=settings.public_base_url,
        on_started=scheduler.start,
        reminders=reminders,
        onedrive=onedrive,
        files=file_store,
        webchat=webchat_store,
        web_chat_secret=settings.web_chat_secret,
        push=push_service,
        vapid_public_key=settings.vapid_public_key,
    )
    return build_app(deps)
