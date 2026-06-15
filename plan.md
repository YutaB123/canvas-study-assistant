# Study Assistant — Plan

## What we're building

A study assistant you text from your phone like a friend. You send it a normal
text message, it texts you back. Behind the scenes it's connected to your UW
Canvas account using your Canvas token, so it knows your real classes,
assignments, and due dates. You can ask it anything about your classes and it
answers using your real data — like what your workload looks like this week,
when your next thing is due, or what a specific assignment is actually asking
for. You can also tell it to remind you about upcoming assignments, and the
reminder shows up as a text at whatever time you choose (for example,
"CSE 163 homework — due in 1 hr"). And you can ask it to turn an assignment or a
reading into flashcards or a practice exam, which it sends back as a clean web
page you can open and study from.

The whole texting experience stays short and casual — like a real person
texting you, not long blocks of formatting.

## The decisions we've made

- **How you text it:** a real phone number through Twilio, so it shows up in your
  Messages app like any other contact.
- **Where it runs:** an always-on cloud host (something like Railway, Render, or
  Fly.io) so it can receive your texts any time and send reminders on schedule,
  even when your computer is off.
- **The brain:** Anthropic's Claude (the Opus 4.8 model) reads your texts and
  writes the replies.
- **Your school:** University of Washington — it talks to canvas.uw.edu using your
  token.
- **Flashcards and practice exams:** delivered as a web page it texts you a link
  to, so the text thread stays short and clean.
- **What it's built with:** Python.

## How it works, start to finish

1. You text the assistant's phone number.
2. Twilio receives your text and hands it to our program.
3. The program first checks that the text actually came from your phone (and
   ignores anyone else), then it immediately tells Twilio "got it" so nothing
   times out while it thinks.
4. It looks at the recent back-and-forth so it remembers context (so a follow-up
   like "what's that one asking for?" makes sense).
5. Claude reads your message and decides what it needs: maybe it looks up your
   assignments, maybe it checks a due date, maybe it sets a reminder, maybe it
   builds you flashcards. It can pull whatever real Canvas data the question
   needs — there's no fixed list of questions, you can genuinely ask anything.
6. Claude writes a short, casual reply.
7. The program sends that reply back to your phone through Twilio.

For reminders, the program keeps its own little schedule. When the set time
arrives, it sends you the reminder text — and it remembers pending reminders even
if the server restarts, so nothing gets lost.

For flashcards and practice exams, it grabs the assignment or reading from
Canvas, has Claude turn it into question-and-answer pairs (or exam questions),
builds a simple web page from them, and texts you the link.

## What gets built (in plain terms)

- **The phone connection** — receiving your texts, sending replies and reminders,
  and making sure only your number is allowed to use it.
- **The brain** — the part that gives Claude its casual-friend personality (short
  texts, no formatting, talks like a person), reads each message, and lets Claude
  use its "tools" to get things done.
- **The Canvas connection** — fetches your courses, assignments, due dates,
  assignment details, and readings from UW Canvas.
- **The tools Claude can use** — looking up courses, looking up assignments,
  reading an assignment's details, checking what's coming up, setting/listing/
  canceling reminders, making flashcards, and making practice exams.
- **The reminder scheduler** — stores your reminders and fires them off as texts
  at the right time, surviving restarts.
- **The study-page maker** — turns an assignment or reading into flashcards or a
  practice exam and publishes it as a web page to link you.
- **A small memory** — keeps the recent conversation and the generated study
  pages.
- **The settings file** — one place to hold your keys and numbers (your Canvas
  token, Anthropic key, Twilio details, your phone number, etc.), kept private
  and never shared.

## How it behaves

- **Texts like a real friend:** a sentence or two, casual, no markdown or bullet
  lists, an emoji now and then. When it sends a study link it just drops it
  naturally ("made you some flashcards: <link>").
- **Reminders in your own words:** you can say "remind me an hour before my 163
  homework" and it figures out the real due date from Canvas, does the math, and
  schedules the text. You can set a reminder for any time you want.
- **Ask anything:** because Claude chooses which Canvas info to pull, you're not
  limited to preset questions.
- **Remembers context:** follow-up questions work without you repeating yourself.

## Keeping it private and safe

- Only your phone number is allowed — texts from anyone else are ignored.
- Every incoming text is verified to actually be from Twilio (not a faker).
- All your keys and tokens live in a private settings file, never committed or
  shared.
- Study-page links use long random web addresses so they aren't guessable.

## The order we'll build it

Each step is useful on its own, so you'll have something working early:

1. **Texting + asking about your classes** — the core. Text it, it answers from
   your real Canvas data ("what's due this week", "when's my next thing",
   "what's this assignment asking for").
2. **Reminders** — setting them and having them arrive as texts on time.
3. **Flashcards** — turn an assignment or reading into a study page it links you.
4. **Practice exams** — same idea, in exam form.

## A couple of things to know

- The cloud host should run as a single copy of the program (not several at
  once), otherwise reminders could fire twice.
- US phone numbers through Twilio need a one-time registration before you can
  text real recipients at scale. A Twilio trial number works right away for
  texting your own verified phone while we build — we'd do the registration
  before calling it "production."

## How we'll know it works

- Confirm the Canvas connection returns your actual upcoming assignments and due
  dates.
- Test the brain on its own (without sending real texts) to confirm the
  short-and-casual replies and that it uses its tools correctly.
- Run it locally, connect it to the Twilio number, text "what's due this week,"
  and get a reply.
- Set a reminder a minute out, confirm the text arrives, and restart the program
  mid-wait to confirm it still fires.
- Ask it to make flashcards and a practice exam, open the links, and check the
  pages look clean.
- After putting it on the cloud host, text the live number and confirm both a
  reply and a scheduled reminder work.
