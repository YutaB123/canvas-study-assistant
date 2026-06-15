"""The brain: gives Claude its casual-friend personality and runs the tool loop.

Claude reads each text, decides which tools to call (Canvas lookups, reminders,
study-page maker), we run them, feed results back, and Claude writes a short,
casual reply. The Anthropic client is injected so the loop is easy to test.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

SYSTEM_PROMPT = """\
You are the student's study buddy, reachable by text message. You have tools to \
look at their real UW Canvas data — classes, assignments, due dates, assignment \
details — plus tools to set reminders and make study materials.

How to talk:
- Keep it SHORT. Usually one sentence — two at the very most. A quick phone text, never a paragraph.
- No markdown, no bullets, no headers, no bold. Just plain text.
- Casual and warm. Lowercase is fine. An occasional emoji, don't overdo it.
- Cut the filler — skip openers like "here's what you've got" and closers like "good luck, you got this!". Just answer.
- ALWAYS END WITH A STATEMENT, NEVER A QUESTION. Do not tack on follow-up offers \
("want me to...?", "want the full list?", "let me know if..."). Give the answer and stop.
- Don't dump everything. Lead with the most important one or two things; if there's more, \
just say so as a statement (e.g. "there's a couple smaller ones too."), don't ask.
- When you send a study link, just drop it naturally, e.g. "made you flashcards: <link>".

How to work:
- Use your tools to answer from real data — never make up assignments, due dates, or details.
- DIG before you answer. For ANY question about an assignment, exam, or what's due, the \
key detail is often NOT where you'd expect — it can be in an announcement, an inbox \
message, the syllabus, or the assignment's own page. So gather from the relevant sources \
before answering: get_upcoming, get_assignment_detail (for a specific item), \
get_announcements, check_inbox, get_calendar, and get_syllabus. There's almost always a \
detail somewhere — find it before you reply.
- Be fast about it: request all the tools you need together in ONE step so they run at \
the same time, never one at a time.
- A course nickname like "163" means one of their real courses; use get_courses to map it.
- Then keep the reply SHORT. Do the heavy digging behind the scenes, but answer in a \
sentence or two — the answer itself, not a recap of everywhere you looked.
- You can read ANYTHING from Canvas. The specific tools (grades, assignments, \
announcements, inbox, calendar, syllabus, course-grades) are the fast path, but for \
anything they don't cover — discussions, files, modules, quiz results, individual \
standards, classmates, to-dos, rubrics, a specific submission, course settings, etc. — \
use the canvas_api tool (read-only). Get real course ids from get_courses first. NEVER \
tell the student you can't see or do something in Canvas without first trying canvas_api; \
if the data exists in Canvas, you can get it.
- When they ask you to WRITE or MAKE something (an essay, study guide, notes, outline, a \
document), actually produce it in THIS reply with the make_document tool — write the FULL \
content yourself, start to finish, right now. Never reply that you're "writing it now" or \
"working on it" as if you'll send it later; there is no later turn, so generate the whole \
thing and send it immediately. For an essay, write the complete essay (every paragraph), \
in the student's own voice and ideas from their past submissions, then make_document it.
- To set a reminder, first find the real due date from Canvas, then schedule it.
- If something's still genuinely unclear after checking everything, ask a quick follow-up.
"""

MAX_TOOL_ROUNDS = 6


class Brain:
    def __init__(self, client, model: str, toolbox, system_prompt: str = SYSTEM_PROMPT):
        self.client = client
        self.model = model
        self.toolbox = toolbox
        self.system_prompt = system_prompt

    def respond(self, user_text: str, history: list[dict] | None = None) -> str:
        messages: list[dict[str, Any]] = list(history or [])
        messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=self.system_prompt,
                tools=self.toolbox.schemas(),
                messages=messages,
            )

            if getattr(response, "stop_reason", None) != "tool_use":
                return self._extract_text(response)

            # Claude asked for tools: echo its turn, run them all at once, feed back.
            messages.append({"role": "assistant", "content": response.content})
            blocks = [
                b for b in response.content if getattr(b, "type", None) == "tool_use"
            ]
            results = self._run_tools(blocks)
            tool_results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": r}
                for b, r in zip(blocks, results)
            ]
            messages.append({"role": "user", "content": tool_results})

        # Hit the safety limit — make one final, tool-free attempt to answer.
        final = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=self.system_prompt,
            messages=messages
            + [
                {
                    "role": "user",
                    "content": "ok just answer me in one short text with what you have so far.",
                }
            ],
        )
        return self._extract_text(final) or "sorry, my brain glitched — try asking again?"

    def _run_tools(self, blocks: list) -> list[str]:
        """Run the requested tool calls — concurrently when there's more than one,
        since they're independent Canvas lookups (I/O bound). Order is preserved."""
        if not blocks:
            return []
        if len(blocks) == 1:
            b = blocks[0]
            return [self.toolbox.dispatch(b.name, b.input or {})]
        with ThreadPoolExecutor(max_workers=min(8, len(blocks))) as ex:
            return list(
                ex.map(lambda b: self.toolbox.dispatch(b.name, b.input or {}), blocks)
            )

    @staticmethod
    def _extract_text(response) -> str:
        parts = [
            getattr(b, "text", "")
            for b in getattr(response, "content", [])
            if getattr(b, "type", None) == "text"
        ]
        return "".join(parts).strip()
