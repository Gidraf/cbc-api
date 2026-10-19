"""The LinkedIn developer series: 300 posts on building with the CBC API.

Ten series of thirty. Each episode is one post and one short video:

* ``I`` idea  — the concept, a question to the audience (text + title card)
* ``D`` demo  — it running in Word, Excel, Sheets or the console
* ``C`` code  — the code typed in the developer frame (services/devcast.py)
* ``B`` build — the finished system, end to end

`calendar` spreads them over days — round-robin across the series, so a
day's posts are never one series five times — using the same planner as
the social export. SCRIPTS holds the episodes already written as devcast
scripts; the rest are titles and hooks waiting for theirs.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

KINDS = {"I": "idea", "D": "demo", "C": "code", "B": "build"}
BASE_TAGS = "#CBC #EdTech #Kenya #BuildInPublic"
FACEBOOK_TAGS = "#developers #programming #coding #KenyaDevs"
POST_PREFIX = "devcast:"            # social_posts.question_id of a developer post
POST_PLATFORMS = ("linkedin", "facebook")

SERIES: list[dict[str, Any]] = [
    {"id": "word-exams", "name": "Exams inside Microsoft Word", "app": "Word",
     "built_on": "/exams, /questions and the maths engine", "tags": "#Office365 #WordAddin #OfficeJS",
     "episodes": [
         ("I", "What if exams ran inside Microsoft Word?", "No new app. No browser. Just Word — and a timer."),
         ("D", "The whole sitting in 60 seconds", "Log in, answer, lock, results, PDF. Watch it all."),
         ("I", "Why Word and not a web app", "Learners practise the tool they'll use at work while they sit the test."),
         ("C", "Scaffolding a Word add-in", "One command gives you a task pane inside Word."),
         ("C", "manifest.xml in 60 seconds", "The one file that tells Office your add-in exists."),
         ("C", "Logging in from the task pane", "Student ID plus exam code becomes a short-lived token."),
         ("C", "Calling the CBC API from Office.js", "fetch() works inside Word. Here's the catch."),
         ("D", "The login screen inside Word", "A sign-in form where you'd expect the ribbon to end."),
         ("C", "One question at a time", "Why the add-in never downloads the whole paper."),
         ("C", "Writing a question into Word with Office.js", "Text, an equation and an answer box, in one Word.run."),
         ("C", "LaTeX to native Word equations", "\\frac{3}{4} in, a real Word equation out."),
         ("D", "Fractions and powers as real equations", "Not screenshots. Editable Word maths."),
         ("C", "Inserting diagrams from the API", "insertInlinePictureFromBase64, explained."),
         ("C", "Answer boxes with content controls", "The Word feature nobody uses — perfect for exams."),
         ("D", "Typing an answer in Word", "It feels like a document. It behaves like a test."),
         ("C", "A countdown for every question", "45 seconds, then the next one loads itself."),
         ("I", "Why the timer lives on the server", "Change your PC clock all you like."),
         ("C", "Locking an answer when time runs out", "cannotEdit = true. One line, no arguments."),
         ("D", "Watching a question lock itself", "Three, two, one… 🔒"),
         ("C", "Submitting answers without sending the key", "The answer key never leaves the server."),
         ("C", "Marking on the server: 3/4 = 0.75 = 6/8", "Equivalent answers are right answers."),
         ("D", "Instant results at the end", "Score, feedback and the working — before they close Word."),
         ("C", "Writing the results page into the document", "A table, a score and a green box."),
         ("C", "Save as PDF from the add-in", "getFileAsync(Office.FileType.Pdf) does the heavy lifting."),
         ("D", "The learner's script as a PDF", "Their answers, their results, one file to keep."),
         ("I", "What Word can't stop: cheating and Copilot", "Honest limits of exams in a word processor."),
         ("I", "Deploying to a whole school", "Microsoft 365 admin: one upload, every learner."),
         ("B", "Full system: a Grade 9 maths sitting in Word", "From login to PDF, nothing skipped."),
         ("B", "Full system: the teacher's view", "Who finished, who struggled, which question broke the class."),
         ("I", "Would your school use this?", "What I learned building exams inside Word."),
     ]},
    {"id": "excel-vba-games", "name": "Maths games in Excel + VBA", "app": "Excel",
     "built_on": "/play/session and /play/check", "tags": "#Excel #VBA #MathsGames",
     "episodes": [
         ("I", "A maths game inside Excel?", "Spreadsheets aren't just for accountants."),
         ("D", "The finished game", "Ten questions, a score, a streak — all in a workbook."),
         ("C", "The Developer tab and your first macro", "Two clicks to unlock VBA."),
         ("C", "Calling a REST API from VBA", "MSXML2 + one function = every API call."),
         ("C", "Parsing JSON in VBA", "VBA-JSON turns a reply into dictionaries."),
         ("C", "Logging in without hard-coding a key", "Anything in a workbook can be read. Plan for it."),
         ("D", "Pick a grade and topic from a dropdown", "Data validation does the UI for you."),
         ("C", "GET /play/session: a round of questions", "Ten questions, shuffled, one request."),
         ("C", "Writing questions into cells", "A loop, a row counter and Cells(r, c)."),
         ("D", "A round loads in one click", "Press the button. Watch the sheet fill."),
         ("C", "Buttons that call macros", "Shapes are buttons if you assign a macro."),
         ("C", "Checking answers with POST /play/check", "3/4, 0.75 and 6/8 — all correct."),
         ("D", "Green for right, red for wrong", "Instant feedback, no formulas to cheat from."),
         ("C", "Score and streak with conditional formatting", "Let Excel do the celebrating."),
         ("C", "A countdown with Application.OnTime", "Excel's built-in scheduler, used as a game clock."),
         ("D", "Beat-the-clock mode", "How many can you get in 60 seconds?"),
         ("C", "Drawing a number line with shapes", "Shapes.AddLine, AddShape and a loop."),
         ("D", "Animated number-line jumps in Excel", "-18 + 12 - 5 + 8, hop by hop."),
         ("C", "Fraction bars from shapes", "Common denominators you can see."),
         ("D", "Fraction bars filling up", "1/3 + 1/4, shown not told."),
         ("C", "A leaderboard sheet", "Sort, rank, crown the winner."),
         ("C", "When the Wi-Fi drops", "On Error, retries and a friendly message."),
         ("I", "Macro security, explained", "Why your .xlsm opens with a red bar."),
         ("C", "Signing your VBA project", "A certificate turns 'blocked' into 'trusted'."),
         ("I", "Why VBA only works on Windows desktop", "Mac, web and mobile: what breaks and why."),
         ("C", "Exporting scores to CSV", "One macro, one file for the teacher."),
         ("D", "A whole class playing in the lab", "Thirty workbooks, one API."),
         ("B", "Full system: the Excel maths game", "Every sheet, every macro, every call."),
         ("B", "Full system: from API to scoreboard", "One question's trip through the workbook."),
         ("I", "What I'd do differently", "And why Office Add-ins are next."),
     ]},
    {"id": "google-apps-script", "name": "Google Forms & Apps Script", "app": "Google Forms and Sheets",
     "built_on": "/play/session and the walkthrough pages", "tags": "#GoogleWorkspace #AppsScript #GoogleForms",
     "episodes": [
         ("I", "Turn an API into Google Forms quizzes", "Every school with Google already has the app."),
         ("D", "One click, a self-marking quiz", "From the question bank to a Form in seconds."),
         ("C", "Apps Script in 60 seconds", "JavaScript that runs on Google's servers."),
         ("C", "UrlFetchApp: calling the CBC API", "The fetch() of Apps Script."),
         ("C", "Keeping the API key in Script Properties", "Not in a cell. Not in the code."),
         ("C", "Building a quiz with FormApp", "setIsQuiz(true) and you're halfway there."),
         ("D", "Multiple choice with auto-marking", "Google marks it. You read the results."),
         ("C", "Feedback for every wrong option", "Each distractor explains itself."),
         ("D", "Learners see why they were wrong", "The best part of a quiz is the feedback."),
         ("C", "A custom menu in Google Sheets", "onOpen() adds your own menu."),
         ("D", "Teacher picks grade, topic and count", "A sheet as a control panel."),
         ("C", "CacheService: one call, many learners", "Don't call the API for every student."),
         ("C", "Short answers with accepted answers", "Fill-in-the-blank, marked automatically."),
         ("D", "Language practice in Forms", "Vocabulary and grammar without Word."),
         ("C", "Posting quizzes to Google Classroom", "Classroom API: assign in one call."),
         ("D", "Assigned to a class in seconds", "Generate, assign, done."),
         ("C", "Reading responses back into Sheets", "Every answer, every learner, one table."),
         ("D", "A class results dashboard", "Which question did everyone miss?"),
         ("I", "Simple vs installable triggers", "The gotcha that silently breaks onEdit."),
         ("C", "Apps Script Web App: doGet + HtmlService", "A whole web page served by a script."),
         ("D", "An animated game as a Web App", "GSAP inside Apps Script. Yes, really."),
         ("C", "google.script.run: marking on the server", "The answer key stays out of the browser."),
         ("D", "Playing on an Android phone", "No install. Just a link."),
         ("C", "Showing the walkthrough animation", "The API's narrated walkthrough, in the Web App."),
         ("I", "Quotas: six minutes and daily limits", "Plan for them before a whole school logs in."),
         ("C", "Weekly revision quizzes on a timer", "Time-driven triggers do it every Friday."),
         ("I", "Why free Google Workspace for Education matters", "Zero licence cost changes what's possible."),
         ("B", "Full system: the Forms quiz generator", "Sheet in, Form out, results back."),
         ("B", "Full system: the Web App game", "Login, play, animations, scores."),
         ("I", "Google or Microsoft for schools?", "My honest take after building both."),
     ]},
    {"id": "notes-copilot", "name": "Notes to Word, made your own with Copilot", "app": "Word with Copilot",
     "built_on": "/curriculum/factory/notes.html and notes.pdf", "tags": "#Copilot #Microsoft365 #Teachers",
     "episodes": [
         ("I", "What if lesson notes arrived ready?", "Teachers spend evenings writing notes. They shouldn't have to."),
         ("D", "A sub-strand's notes, generated and printed", "Grade 9 Integers, start to finish."),
         ("C", "GET /factory/notes.html", "One request, a whole set of notes."),
         ("C", "Notes as a PDF in one call", "Print-ready, diagrams included."),
         ("D", "Opening the notes in Word", "HTML in, an editable document out."),
         ("C", "HTML notes into Word, cleanly", "Styles that survive the trip."),
         ("D", "Copilot: summarise these notes", "Ten pages into one."),
         ("D", "Copilot: five revision questions from the notes", "Notes become practice in seconds."),
         ("I", "Make it your own", "Why teachers must edit AI content, not just print it."),
         ("D", "Copilot: rewrite for a struggling reader", "Same idea, simpler words."),
         ("D", "Copilot: translate a section into Kiswahili", "Bilingual notes, then a human check."),
         ("C", "Fetching notes by grade and sub-strand", "The query parameters that matter."),
         ("C", "Notes with diagrams that actually exist", "Matching planned figures to real ones."),
         ("D", "Diagrams where the notes need them", "No more hatched placeholders."),
         ("C", "A Word macro that pulls today's notes", "One button in the ribbon."),
         ("D", "One button: today's notes in Word", "Click, and the lesson is there."),
         ("I", "Five Copilot prompts for teachers", "Prompts that save real time."),
         ("D", "Copilot: a one-page summary sheet", "The page learners actually keep."),
         ("D", "Copilot: a quiz table from the notes", "Questions, answers, marks — in a table."),
         ("C", "Adding the school letterhead automatically", "Headers and logos with Office.js."),
         ("D", "Branded notes in one click", "Every page looks like your school's."),
         ("C", "Notes and questions in one document", "Combining two endpoints into one pack."),
         ("D", "A revision pack", "Notes, worked examples and questions together."),
         ("I", "How the API checks its own notes", "Integrity checks before a teacher sees anything."),
         ("C", "A term's notes as one book", "Every sub-strand, one PDF."),
         ("D", "Learners using Copilot for flash cards", "Active recall, made in Word."),
         ("I", "Copilot for learners: rules for honest use", "Help to learn, not to skip learning."),
         ("B", "Full system: notes to a personal revision pack", "From the API to a learner's own copy."),
         ("B", "Full system: a teacher's weekly workflow", "Monday morning, sorted."),
         ("I", "What teachers said after trying it", "The feedback that changed the design."),
     ]},
    {"id": "lesson-plans", "name": "Lesson plans straight from the system", "app": "Word and Excel",
     "built_on": "the lesson plan, notes and activities stations", "tags": "#LessonPlanning #Teachers #CBE",
     "episodes": [
         ("I", "A CBC lesson plan in seconds", "One a teacher would actually use."),
         ("D", "Six lessons for one sub-strand", "Outcomes, experiences, assessment — dealt out."),
         ("I", "Why AI lesson plans repeat themselves", "And how we stopped lesson 6 copying lesson 3."),
         ("C", "Dealing outcomes to lessons, deterministically", "The model doesn't choose. The code does."),
         ("C", "Handing lesson N's ending to lesson N+1", "A hand-off that keeps a plan coherent."),
         ("D", "A lesson plan in the KICD format", "The layout teachers already know."),
         ("C", "Generating notes for a sub-strand", "POST /factory/generate-notes."),
         ("C", "Planning activities", "POST /factory/plan-activities."),
         ("D", "Practical activities with materials lists", "What to bring, what to do, what to ask."),
         ("C", "Pulling activities into the plan", "Every station's work, in one document."),
         ("D", "The lesson plan in Word, with tables", "Editable, printable, yours."),
         ("C", "Building the plan table with Office.js", "Rows, columns and a header style."),
         ("D", "Editing the plan with Copilot", "Shorter, longer, for a mixed class."),
         ("I", "Words, not directions", "Don't tell teachers to find a story. Write it."),
         ("D", "Lesson materials ready to read aloud", "The story, the song, the script."),
         ("C", "Planning visuals for each lesson", "POST /factory/plan-visuals."),
         ("D", "Visual aids matched to the lesson", "The diagram the notes describe, not a generic one."),
         ("C", "A term's scheme of work", "Weeks, lessons and outcomes in one call."),
         ("D", "The scheme of work in Excel", "A term on one sheet."),
         ("C", "Linking assessment to every lesson", "Questions tagged to the outcome they test."),
         ("D", "Exit tickets from the question bank", "Three questions to end every lesson."),
         ("C", "Exporting a lesson plan as a PDF", "Same renderer as the notes."),
         ("D", "A print-ready lesson plan", "From the API to the staffroom printer."),
         ("I", "Teacher in the loop", "Review and approve before anything is used."),
         ("C", "The approval workflow behind every plan", "Artifacts, versions and reviewers."),
         ("D", "A reviewer marks a plan ready", "One click, with a history behind it."),
         ("I", "Same lesson, three levels", "Differentiation without three times the work."),
         ("B", "Full system: sub-strand to lesson plan in Word", "Every step, no cuts."),
         ("B", "Full system: a teacher's week, planned", "Five days in five minutes."),
         ("I", "Could this give teachers their evenings back?", "What I hope this becomes."),
     ]},
    {"id": "walkthrough-videos", "name": "Animated walkthroughs & whiteboard videos", "app": "the browser",
     "built_on": "/play/items/{id}/walkthrough.html, whiteboard.html and /video", "tags": "#GSAP #Animation #ffmpeg",
     "episodes": [
         ("I", "Every question deserves a teacher at the board", "So we built one that never gets tired."),
         ("D", "A narrated walkthrough in the browser", "Scene by scene, in a Kenyan voice."),
         ("C", "The walkthrough scenes JSON", "The script every animation reads."),
         ("C", "GSAP: animating a number line", "Ticks, arcs and a landing point."),
         ("D", "Number-line jumps, voiced", "Start at -18. Jump. Land."),
         ("C", "The balance model for equations", "Whatever you do to one side…"),
         ("D", "Solving 3x + 5 = 20 on a scale", "Equations you can see balance."),
         ("C", "Fraction bars and common denominators", "Cut both bars into twelfths."),
         ("D", "Fraction bars in motion", "Different pieces, same size, then add."),
         ("C", "BODMAS, step by step", "Each rewrite says why."),
         ("D", "A BODMAS walkthrough", "Brackets first — watch."),
         ("C", "A Kenyan neural voice with edge-tts", "Asilia and Chilemba, free."),
         ("C", "Making LaTeX speakable", "\\frac{3}{4} is 'three quarters', not 'backslash frac'."),
         ("D", "'12 m' becomes '12 metres'", "The board shows symbols. The voice says words."),
         ("C", "Headless Chrome, frame by frame", "window.__seek(t) and a screenshot."),
         ("C", "ffmpeg: laying the voice over the frames", "adelay, amix and one command."),
         ("D", "From HTML to MP4", "A page becomes a video."),
         ("C", "A hand that writes", "Following the stroke, frame by frame."),
         ("D", "The whiteboard hand", "It writes the working as it's spoken."),
         ("C", "Captions for sound-off scrolling", "A phrase at a time, in sync."),
         ("D", "The vertical cut for TikTok and Reels", "1080×1920, safe areas respected."),
         ("C", "Countdown ticks: pause and try", "Three seconds to think, with a tick each."),
         ("C", "One video per version of a question", "Hash the script, cache the MP4."),
         ("C", "The render queue: one browser at a time", "Why renders get their own lane."),
         ("D", "A topic's worth of videos in one batch", "Forty videos, one request."),
         ("I", "The engine computes, not the model", "Every number in a video is checked arithmetic."),
         ("C", "The developer theme you're watching", "This VS Code frame is a renderer too."),
         ("B", "Full system: question to narrated video", "Bank to MP4, no hands."),
         ("B", "Full system: 100 videos overnight", "Queue at 10 pm, publish at 7 am."),
         ("I", "What learners watched most", "And what they skipped."),
     ]},
    {"id": "ai-agents-mcp", "name": "AI agents, MCP and bring-your-own-model", "app": "VS Code and Claude Code",
     "built_on": "the agent API and the CBC MCP server", "tags": "#AIAgents #MCP #LLM #GitHubCopilot",
     "episodes": [
         ("I", "Bring your own model to a curriculum platform", "The platform builds the prompt. Your model answers."),
         ("D", "An agent generating CBC questions via MCP", "Claude Code, fifty questions, one instruction."),
         ("C", "What is MCP?", "A USB port for AI tools, in 60 seconds."),
         ("C", "The CBC MCP server over stdio", "A Python file your agent can talk to."),
         ("C", "Configuring .mcp.json", "Three lines and your agent has new tools."),
         ("D", "Copilot calling CBC tools", "From a chat message to a question bank."),
         ("C", "The platform builds the prompt, your model answers", "Why we split it that way."),
         ("C", "Routing: OpenAI, Anthropic, Gemini, Ollama", "Four providers behind one interface."),
         ("D", "Per-stage model selection", "A cheap model drafts, a strong one reviews."),
         ("C", "Running locally with Ollama", "No API bill. No data leaving the room."),
         ("D", "A free local model writing questions", "Slower, and good enough for drafts."),
         ("C", "Langfuse: every prompt versioned", "Change a prompt, keep the old one."),
         ("D", "Tracing one generation end to end", "Every call, token and cost."),
         ("C", "Validation contracts: rejecting bad JSON", "The model's output is untrusted input."),
         ("C", "Claim verification: catching made-up facts", "Check the evidence before it's published."),
         ("D", "A question rejected, and why", "The reviewer you never see."),
         ("C", "Model scout: testing new models weekly", "New model out? It sits the same exam."),
         ("D", "Comparing models on the same task", "Same prompt, five models, one scoreboard."),
         ("C", "Agent night: queue work while you sleep", "The overnight shift."),
         ("D", "Waking up to 500 reviewed questions", "What the night produced."),
         ("I", "Cost per question: what we measured", "Real numbers, not guesses."),
         ("C", "API keys per agent, scoped by role", "An agent gets what it needs, no more."),
         ("I", "Agents need guardrails", "The rules we wrote after things went wrong."),
         ("C", "Human review before publishing", "Nothing reaches a learner unread."),
         ("D", "The reviewer console in action", "Approve, reject, regenerate."),
         ("C", "Webhooks: tell me when a job finishes", "Stop polling."),
         ("I", "Which model writes the best maths questions?", "The answer surprised me."),
         ("B", "Full system: an agent filling a question bank", "One prompt, a topic covered."),
         ("B", "Full system: prompt to published", "Every gate a question passes."),
         ("I", "Where AI agents in education go next", "My bets for the next year."),
     ]},
    {"id": "maths-engine", "name": "The maths engine, diagrams and graphs", "app": "Word and Excel",
     "built_on": "/math/solve, /math/verify, /math/render-graph and diagrams", "tags": "#Python #Maths #STEM",
     "episodes": [
         ("I", "Never trust an LLM with arithmetic", "Language models guess. Engines compute."),
         ("D", "The maths engine solving step by step", "Every step, every reason."),
         ("C", "POST /math/solve", "An expression in, working out."),
         ("C", "POST /math/verify", "Checking a model's answer before a learner sees it."),
         ("D", "Catching a wrong answer key", "The model said B. The engine said A."),
         ("C", "Exact fractions with Python's Fraction", "0.1 + 0.2 is not a maths lesson."),
         ("C", "Equations from text: /math/extract-equations", "A word problem becomes an expression."),
         ("D", "A word problem becomes an equation", "Read, extract, solve."),
         ("C", "Graphs with /math/render-graph", "y = 2x + 3, print-ready."),
         ("D", "Plotting for a worksheet", "Axes, labels, gridlines — done."),
         ("C", "Diagrams from a one-line brief", "Describe it, get an SVG."),
         ("D", "A labelled triangle from one sentence", "Sides, angles, marks."),
         ("C", "SVG diagrams you can print", "Sharp at any size."),
         ("D", "Diagrams inside an exam paper", "Placed, numbered, referenced."),
         ("C", "Simulations: /math/simulate", "Run the scenario, read the numbers."),
         ("D", "A rates-of-work simulation", "Two teams, one tank, real rates."),
         ("C", "The formulas library: /math/formulas", "Every formula a grade needs."),
         ("D", "A Grade 9 formula sheet", "Generated, not typed."),
         ("C", "Narrated steps: /math/narrate-step", "Working that can be read aloud."),
         ("C", "Print rendering: /math/render-print", "From steps to a printable page."),
         ("D", "A worked solution, print-ready", "The page a teacher hands out."),
         ("C", "Graphs inside Excel", "The API's data, Excel's chart."),
         ("D", "An Excel chart from the API", "Live data, no copy-paste."),
         ("C", "Diagrams inside Word", "insertInlinePictureFromBase64 again — now with SVG."),
         ("D", "A Word worksheet with diagrams", "Questions and figures, together."),
         ("I", "Why every diagram is reviewed", "A wrong label teaches a wrong idea."),
         ("C", "Authoring a question from a diagram", "Start with the picture, write the question."),
         ("B", "Full system: a verified maths pipeline", "Nothing published without the engine's yes."),
         ("B", "Full system: a worksheet with graphs and diagrams", "From brief to print."),
         ("I", "Accuracy first", "What our checks catch every week."),
     ]},
    {"id": "building-the-api", "name": "Building the CBC API", "app": "the console",
     "built_on": "FastAPI, Postgres, Redis, Celery and MinIO", "tags": "#FastAPI #Python #SoftwareArchitecture",
     "episodes": [
         ("I", "I built a curriculum content factory", "Here's the architecture."),
         ("D", "A tour of the admin console", "Everything a content team needs."),
         ("C", "The FastAPI project layout", "Routes, services, infra — and why."),
         ("C", "Docker Compose: the whole stack", "One command, every service."),
         ("C", "Migrations on startup", "The database is ready before the first request."),
         ("C", "Redis and Celery: the job queue", "Work that outlives a request."),
         ("D", "Jobs flowing through the queue", "Queued, running, done."),
         ("C", "The duplicate-job bug that ate our pipeline", "Every stage after the first vanished."),
         ("C", "Object storage with MinIO", "Videos, diagrams and PDFs."),
         ("C", "JWT auth and roles", "Admin, operator, reviewer, developer, user."),
         ("C", "API keys hashed, never stored", "SHA-256 and a last-used timestamp."),
         ("D", "Swagger docs as a product", "/docs is the first thing partners open."),
         ("C", "Question DNA: every item's lineage", "Where it came from, what changed."),
         ("C", "Artifact versions and layered review", "Nothing is overwritten."),
         ("D", "A question's history", "Every version, every reviewer."),
         ("C", "Curriculum coverage tracking", "Which outcomes have no questions yet?"),
         ("D", "The coverage dashboard", "Gaps, in red."),
         ("C", "Daily generation targets", "How many, which topics, by when."),
         ("C", "Playwright as a browsing service", "A real browser for agents and renders."),
         ("C", "Logs you can search from the console", "No SSH required."),
         ("C", "Testing: hundreds of tests and counting", "The suite that lets me ship on Fridays."),
         ("C", "Tests that read like requirements", "test_a_render_is_not_held_by_its_topics_content_work."),
         ("I", "Name tests after the bug they prevent", "A test name is documentation."),
         ("C", "One shape for every error", "Codes, messages, no stack traces."),
         ("C", "Roles and limits for public endpoints", "Open enough to use, closed enough to trust."),
         ("C", "The exam builder: bank to paper", "Pick, balance, render."),
         ("D", "An exam paper PDF with marking scheme", "Ready for the printer."),
         ("B", "Full system: the architecture walkthrough", "Every box, every arrow."),
         ("B", "Full system: one question's journey", "From prompt to paper to video."),
         ("I", "What I'd tell myself on day one", "Lessons from building it."),
     ]},
    {"id": "social-automation", "name": "From question bank to social feed", "app": "the console",
     "built_on": "/play/social, /play/social/book and the poster", "tags": "#Automation #ContentCreation #SocialMedia",
     "episodes": [
         ("I", "From a question bank to 300 posts", "Content as a by-product of the product."),
         ("D", "One question becomes a vertical video", "Hook, countdown, solution, follow."),
         ("C", "Generating the post text", "Question, options, answer, working, hashtags."),
         ("C", "Hashtags from the curriculum", "The grade and topic write their own tags."),
         ("D", "Brand settings: colours, voice, handle", "Every video on brand, automatically."),
         ("C", "Booking a month of posts", "POST /play/social/book."),
         ("D", "The content calendar", "Five to fifteen a day, never the same question twice."),
         ("C", "Random times inside posting hours", "Human-looking schedules."),
         ("C", "Caps per platform and gaps between posts", "Rules that protect the account."),
         ("D", "The browser poster", "A real browser, logged in once."),
         ("C", "Why the rules live on the server", "The browser only does what it's told."),
         ("C", "Heartbeats and commands", "Is the poster alive? What should it do next?"),
         ("D", "Posting to Facebook groups", "Where Kenyan parents and teachers are."),
         ("C", "Moving videos to Google Drive", "MinIO for work, Drive for keeping."),
         ("D", "The Drive library, organised", "By grade, subject and topic."),
         ("C", "Tracking views, likes and follows", "One row per post per platform."),
         ("D", "Which topics grew followers", "Data, not guesses."),
         ("C", "An export ZIP for any scheduler", "Videos, captions and schedule.csv."),
         ("D", "Bulk upload to a scheduler", "A month in one upload."),
         ("C", "Thumbnails at the right frame", "The question under the hook."),
         ("C", "Music under the voice", "10% volume, fade in, fade out."),
         ("D", "Before and after: music and captions", "Same video, twice the watch time."),
         ("I", "TikTok vs LinkedIn", "Different audiences, different videos."),
         ("C", "A developer cut: this VS Code theme", "The renderer behind this series."),
         ("D", "Rendering this series with the system", "The series about the system, made by the system."),
         ("C", "LinkedIn post text, generated", "Hook, title, part number, call to action."),
         ("I", "Posting five a day: what the data says", "More isn't always more."),
         ("B", "Full system: the content engine end to end", "Question in, published post out."),
         ("B", "Full system: a month on autopilot", "What runs, what I still check."),
         ("I", "300 posts later", "What worked, what didn't, what's next."),
     ]},
]

_KIND_LINE = {
    "I": "💡 An idea I'm exploring — tell me where it breaks.",
    "D": "🎥 Watch it run in {app}.",
    "C": "💻 Every line of code is in the video.",
    "B": "🚀 The full system, end to end.",
}


def episodes(series_id: str = "") -> list[dict[str, Any]]:
    """Every episode, in series order, with its post text."""
    out = []
    for s in SERIES:
        if series_id and s["id"] != series_id:
            continue
        eps = s["episodes"]
        for n, (kind, title, hook) in enumerate(eps, start=1):
            eid = f"{s['id']}-{n:02d}"
            nxt = eps[n][1] if n < len(eps) else ""
            out.append({"id": eid, "series": s["id"], "series_name": s["name"], "episode": n, "of": len(eps),
                        "kind": KINDS[kind], "title": title, "hook": hook, "has_script": eid in SCRIPTS,
                        "post": post_text(s, n, kind, title, hook, nxt),
                        "facebook_post": post_text(s, n, kind, title, hook, nxt, platform="facebook")})
    return out


def post_text(s: dict[str, Any], n: int, kind: str, title: str, hook: str, next_title: str = "",
              platform: str = "linkedin") -> str:
    """LinkedIn: the build-in-public story. Facebook: shorter, for developers
    scrolling a feed — what it is, the stack, the next part."""
    if platform == "facebook":
        follow = (f"👉 Follow for part {n + 1}: {next_title}" if next_title
                  else "👇 That's the series. What should I build next?")
        return "\n\n".join([
            f"👨‍💻 {hook}",
            f"{title} — {s['name']}, part {n}/{len(s['episodes'])}.",
            _KIND_LINE[kind].format(app=s["app"]),
            f"Stack: {s['built_on']}.",
            follow,
            f"{FACEBOOK_TAGS} {s['tags']}",
        ])
    follow = (f"♻️ Follow for part {n + 1}: {next_title}" if next_title
              else "That's the series. What should I build next? 👇")
    return "\n\n".join([
        hook,
        f"{title}\n{s['name']} · Part {n}/{len(s['episodes'])}",
        _KIND_LINE[kind].format(app=s["app"]),
        f"Built on the CBC API — {s['built_on']}.",
        follow,
        f"{BASE_TAGS} {s['tags']}",
    ])


def calendar(start: date, *, per_day: int = 2, times: list[str] | None = None) -> list[dict[str, Any]]:
    """Every episode with a date and time: one series after another within a
    day, each series one episode further every time its turn comes round."""
    from .social_export import plan

    by_series = [episodes(s["id"]) for s in SERIES]
    order = [eps[k] for k in range(max(len(e) for e in by_series)) for eps in by_series if k < len(eps)]
    slots = times or ["07:30", "12:30", "17:30", "20:00", "21:30"]
    when = plan(len(order), start=start, per_day=per_day, times=slots)
    return [{"number": i + 1, "date": f"{at:%Y-%m-%d}", "time": f"{at:%H:%M}", "timezone": "EAT (UTC+3)",
             "platform": "linkedin", **ep} for i, (ep, at) in enumerate(zip(order, when))]


def _episode(eid: str) -> dict[str, Any] | None:
    return next((e for e in episodes(eid.rsplit("-", 1)[0]) if e["id"] == eid), None)


def media(post_key: str, platform: str) -> dict[str, Any]:
    """For the poster: the episode's video as it stands, the caption for this
    platform and a title. An episode with no script yet has no video."""
    from . import devcast

    eid = post_key.removeprefix(POST_PREFIX)
    ep = _episode(eid)
    if not ep:
        return {"status": "none", "error": f"No episode {eid}."}
    text = ep["facebook_post"] if platform == "facebook" else ep["post"]
    if eid not in SCRIPTS:
        return {"status": "none", "post": text, "title": ep["title"], "error": "No script written yet."}
    return {**devcast.status(SCRIPTS[eid]), "post": text, "title": ep["title"]}


def book(*, start: date | None = None, per_day: int = 2, times: list[str] | None = None,
         platforms: list[str] | None = None, dry: bool = False, created_by: str = "") -> dict[str, Any]:
    """Put the written episodes on the poster's calendar, in series rotation,
    after the last developer post booked; their videos not made yet are
    queued. Each platform gets the episode a gap apart. Running it again
    books only what is new — episodes whose scripts were written since."""
    from ..infra.db import execute, fetch_all, fetch_one
    from . import devcast
    from .social_export import EAT, _post_id, plan, poster_rules

    platforms = [p for p in (platforms or list(POST_PLATFORMS)) if p in POST_PLATFORMS]
    if not platforms:
        raise ValueError("Pick at least one of: " + ", ".join(POST_PLATFORMS))
    booked = {(r["question_id"], r["platform"]) for r in (fetch_all(
        "SELECT question_id, platform FROM social_posts WHERE audience = 'developers'") or [])}
    order = [r for r in calendar(date.today(), per_day=1) if r["has_script"]]
    todo = [(ep, [p for p in platforms if (POST_PREFIX + ep["id"], p) not in booked]) for ep in order]
    todo = [(ep, ps) for ep, ps in todo if ps]
    last = fetch_one("""SELECT MAX(scheduled_for) AS t FROM social_posts
                        WHERE audience = 'developers' AND status <> 'gave_up'""") or {}
    first = start or datetime.now(EAT).date() + timedelta(days=1)
    if last.get("t"):
        first = max(first, last["t"].astimezone(EAT).date() + timedelta(days=1))
    slots = times or ["07:30", "12:30", "17:30", "20:00", "21:30"]
    when = plan(len(todo), start=first, per_day=per_day, times=slots)
    gap = timedelta(minutes=int(poster_rules()["min_gap_minutes"]) + 5)
    posts, to_render = [], []
    for (ep, ps), at in zip(todo, when):
        for k, platform in enumerate(ps):
            posts.append({"id": ep["id"], "title": ep["title"], "platform": platform, "at": at + k * gap})
        st = devcast.status(SCRIPTS[ep["id"]])
        if st["status"] in ("none", "failed"):
            to_render.append(ep["id"])
    if not dry:
        for p in posts:
            ep = _episode(p["id"]) or {}
            execute(
                """INSERT INTO social_posts (post_id, question_id, platform, audience, grade, subject, sub_strand,
                                            scheduled_for, created_by)
                   VALUES (:id, :qid, :platform, 'developers', '', 'Developers', :ss, :at, :by)
                   ON CONFLICT (post_id) DO NOTHING""",
                {"id": _post_id(POST_PREFIX + p["id"], p["platform"]), "qid": POST_PREFIX + p["id"],
                 "platform": p["platform"], "ss": ep.get("series_name", ""), "at": p["at"], "by": created_by})
        for eid in to_render:
            devcast.enqueue(SCRIPTS[eid], queued_by=created_by or "devcast-plan")
    unwritten = sum(1 for e in episodes() if not e["has_script"])
    return {"booked": not dry, "platforms": platforms, "episodes": len(todo), "posts": len(posts),
            "to_render": len(to_render), "waiting_for_scripts": unwritten,
            "schedule": [{**p, "at": p["at"].astimezone(EAT).isoformat()} for p in posts]}


# ── episodes written as devcast scripts ──────────────────────────────────────

SCRIPTS: dict[str, dict[str, Any]] = {
    "word-exams-10": {
        "id": "word-exams-10", "title": "Writing a question into Word with Office.js", "format": "square",
        "scenes": [
            {"scene": "title", "kicker": "Exams inside Word · Part 10/30",
             "text": "Writing a question into Word with Office.js",
             "say": "Part ten. Let's put an exam question, a real equation and an answer box into a Word document "
                    "from our add-in."},
            {"scene": "code", "file": "src/taskpane/exam.js", "lang": "js", "highlight": [4, 5, 7, 8],
             "code": "export async function showQuestion(q, n, total) {\n"
                     "  await Word.run(async (context) => {\n"
                     "    const body = context.document.body;\n"
                     "    body.clear();\n"
                     "    body.insertParagraph(`Question ${n} of ${total}`, \"End\").styleBuiltIn = \"Heading2\";\n"
                     "    body.insertParagraph(q.text, \"End\");\n"
                     "    if (q.ooxml) body.insertOoxml(q.ooxml, \"End\");\n"
                     "    const box = body.insertParagraph(\"\", \"End\").insertContentControl();\n"
                     "    box.tag = `answer:${q.id}`;\n"
                     "    box.title = \"Answer\";\n"
                     "    await context.sync();\n"
                     "  });\n"
                     "}",
             "say": "Everything happens inside Word dot run. We clear the page, write a heading, then the question. "
                    "The equation arrives from the API as Office Open XML, so it lands as a native Word equation. "
                    "Last, a content control: the learner's answer box, tagged with the question's ID."},
            {"scene": "word", "file": "Grade9-Maths-Exam.docx",
             "doc": [{"h": "Question 3 of 10"}, {"q": "Work out, giving your answer as a fraction in its simplest form:",
                                                 "n": "", "marks": 2},
                     {"eq": "¾ + ⅛ − ½"}, {"box": ""}],
             "pane": {"title": "CBC Exams", "fields": [["Student", "STU-0423"], ["Exam", "G9-MATHS-T3"]],
                      "timer": [45, 31], "progress": [3, 10], "button": "Next ▶"},
             "say": "And this is what the learner sees. The question, a real equation, and an answer box. "
                    "The task pane shows who is sitting, the exam, and the clock."},
            {"scene": "code", "file": "src/taskpane/exam.js", "lang": "js", "prefilled": 13, "highlight": [20],
             "code": "export async function showQuestion(q, n, total) {\n"
                     "  await Word.run(async (context) => {\n"
                     "    const body = context.document.body;\n"
                     "    body.clear();\n"
                     "    body.insertParagraph(`Question ${n} of ${total}`, \"End\").styleBuiltIn = \"Heading2\";\n"
                     "    body.insertParagraph(q.text, \"End\");\n"
                     "    if (q.ooxml) body.insertOoxml(q.ooxml, \"End\");\n"
                     "    const box = body.insertParagraph(\"\", \"End\").insertContentControl();\n"
                     "    box.tag = `answer:${q.id}`;\n"
                     "    box.title = \"Answer\";\n"
                     "    await context.sync();\n"
                     "  });\n"
                     "}\n"
                     "\n"
                     "export async function lockAnswer(qid) {\n"
                     "  return Word.run(async (context) => {\n"
                     "    const box = context.document.contentControls.getByTag(`answer:${qid}`).getFirst();\n"
                     "    box.load(\"text\");\n"
                     "    await context.sync();\n"
                     "    box.cannotEdit = true;\n"
                     "    await context.sync();\n"
                     "    return box.text;\n"
                     "  });\n"
                     "}",
             "say": "When the time is up, we find the answer box by its tag, read what was typed, and set cannot "
                    "edit to true. One line, and the answer is locked."},
            {"scene": "word", "file": "Grade9-Maths-Exam.docx", "reveal": False,
             "doc": [{"h": "Question 3 of 10"}, {"q": "Work out, giving your answer as a fraction in its simplest form:",
                                                 "n": "", "marks": 2},
                     {"eq": "¾ + ⅛ − ½"}, {"box": "3/8", "locked": True}],
             "pane": {"title": "CBC Exams", "fields": [["Student", "STU-0423"], ["Exam", "G9-MATHS-T3"]],
                      "timer": [3, 0], "progress": [3, 10], "lines": ["Time's up — answer saved."]},
             "say": "Three, two, one. Locked, saved, and the next question loads."},
            {"scene": "points", "title": "Lock on the client, check on the server",
             "items": ["The countdown in Word is only a display",
                       "The API records when each question was sent and rejects late answers",
                       "cannotEdit stops edits after time is up",
                       "The answer key never reaches the learner's machine"],
             "say": "One rule for exams in Word: lock on the client, but trust only the server. The server knows when "
                    "each question was sent, rejects late answers, and keeps the answer key to itself."},
            {"scene": "outro", "text": "Part 11: LaTeX → native Word equations", "cta": "Follow for the series",
             "say": "Next time: turning LaTeX into native Word equations. Follow so you don't miss it."},
        ],
    },
    "excel-vba-games-04": {
        "id": "excel-vba-games-04", "title": "Calling a REST API from VBA", "format": "square",
        "scenes": [
            {"scene": "title", "kicker": "Maths games in Excel · Part 4/30", "text": "Calling a REST API from VBA",
             "sub": "MSXML2, a bearer token and VBA-JSON",
             "say": "Part four. Let's make Excel talk to the CBC API using nothing but VBA."},
            {"scene": "code", "file": "GameModule.bas", "lang": "vba", "highlight": [6, 7, 10],
             "code": "Private Const BASE_URL As String = \"https://api.example.com/api/v1\"\n"
                     "Private token As String\n"
                     "\n"
                     "Function Api(method As String, path As String, Optional payload As Object) As Object\n"
                     "    Dim http As Object: Set http = CreateObject(\"MSXML2.ServerXMLHTTP.6.0\")\n"
                     "    http.Open method, BASE_URL & path, False\n"
                     "    http.setRequestHeader \"Authorization\", \"Bearer \" & token\n"
                     "    http.setRequestHeader \"Content-Type\", \"application/json\"\n"
                     "    If payload Is Nothing Then http.send Else http.send JsonConverter.ConvertToJson(payload)\n"
                     "    If http.Status <> 200 Then Err.Raise vbObjectError + http.Status, \"API\", http.responseText\n"
                     "    Set Api = JsonConverter.ParseJson(http.responseText)\n"
                     "End Function",
             "say": "One function does every call. It opens a request, sends our token as a bearer header, and turns "
                    "any error into a proper VBA error. The reply is parsed with VBA-JSON into dictionaries and "
                    "collections."},
            {"scene": "terminal",
             "cmd": "curl -s \"$API/play/session?grade=Grade%209&subject=Mathematics&mode=choice&count=1\" "
                    "-H \"Authorization: Bearer $TOKEN\" | jq '.items[0].question_text'",
             "output": ["\"A diver at -18 m rises 12 m, drops 5 m, then rises 8 m. Where is she now?\""],
             "say": "Here is the same call from the terminal, so you can see exactly what Excel receives."},
            {"scene": "code", "file": "GameModule.bas", "lang": "vba", "prefilled": 13, "highlight": [16, 21],
             "code": "Private Const BASE_URL As String = \"https://api.example.com/api/v1\"\n"
                     "Private token As String\n"
                     "\n"
                     "Function Api(method As String, path As String, Optional payload As Object) As Object\n"
                     "    Dim http As Object: Set http = CreateObject(\"MSXML2.ServerXMLHTTP.6.0\")\n"
                     "    http.Open method, BASE_URL & path, False\n"
                     "    http.setRequestHeader \"Authorization\", \"Bearer \" & token\n"
                     "    http.setRequestHeader \"Content-Type\", \"application/json\"\n"
                     "    If payload Is Nothing Then http.send Else http.send JsonConverter.ConvertToJson(payload)\n"
                     "    If http.Status <> 200 Then Err.Raise vbObjectError + http.Status, \"API\", http.responseText\n"
                     "    Set Api = JsonConverter.ParseJson(http.responseText)\n"
                     "End Function\n"
                     "\n"
                     "Sub NewRound()\n"
                     "    Dim res As Object, item As Object, r As Long\n"
                     "    Set res = Api(\"GET\", \"/play/session?grade=Grade%209&subject=Mathematics&mode=choice&count=10\")\n"
                     "    r = 2\n"
                     "    With Sheets(\"Game\")\n"
                     "        .Range(\"A2:E50\").ClearContents\n"
                     "        For Each item In res(\"items\")\n"
                     "            .Cells(r, 1) = r - 1: .Cells(r, 2) = item(\"question_text\")\n"
                     "            r = r + 1\n"
                     "        Next\n"
                     "    End With\n"
                     "End Sub",
             "say": "Now a round. Ask for ten Grade 9 questions, clear the sheet, and write each question into its "
                    "own row."},
            {"scene": "excel", "file": "MathsGame.xlsm", "sheet": "Game", "select": "D3", "formula": "3/4",
             "widths": [6, 46, 12, 15, 21],
             "rows": [["#", "Question", "Options", "Your answer", "Result"],
                      ["1", "A diver at -18 m rises 12 m, drops 5 m…", "A–D", "A", "✓ Correct"],
                      ["2", "Work out ½ + ¼", "", "3/4", "✓ Correct"],
                      ["3", "Solve 3x + 5 = 20", "", "4", "✗ Try again"],
                      ["4", "Simplify 2(x + 3) − x", "A–D", "", ""]],
             "say": "Click New round and the questions land in the sheet. Type an answer, and the result comes back "
                    "from the API. Three quarters, nought point seven five or six eighths: all correct."},
            {"scene": "points", "title": "Gotchas",
             "items": ["Windows desktop Excel only — Mac has no MSXML2",
                       "Downloaded .xlsm files have macros blocked: unblock or sign",
                       "Never put an admin key in a workbook — anyone can read VBA",
                       "Build JSON with ConvertToJson, never by joining strings"],
             "say": "Four gotchas. It's Windows desktop only. Downloaded workbooks have their macros blocked. "
                    "Anyone can read your VBA, so never ship an admin key. And build JSON with Convert to JSON, "
                    "never by gluing strings together."},
            {"scene": "outro", "text": "Part 5: parsing JSON in VBA", "cta": "Follow for the series",
             "say": "Next time: parsing JSON in VBA properly. Follow so you don't miss it."},
        ],
    },
}
