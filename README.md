# assist: the Work Assistant That Remembers

A command-line helper for a small agency. Every day it reads the team's work records (mails, chats, docs, tasks, meetings) and:

- writes a **brief before each meeting**: what changed, who promised what, what to open, one question to ask
- **answers short questions** like "Who owns billing for NB?"
- **remembers feedback**: corrections, preferences, "forget this"
- **cites a source** (record id) for every line
- **never shows anyone what they are not allowed to see**

It uses **no AI model and no API key**. Plain Python rules do the work, so every answer comes from the data and costs 0 tokens.

---

## 1. Setup

- Python 3.9 or newer
- **Nothing to install**: it uses only the Python standard library

Put this repo and the organisers' data pack **side by side**:

```
Desktop\
  ├── assist\                     <- this repo (assist.py, README.md, DESIGN.md, .gitignore)
  └── BuildSprint-R3-candidate\   <- organisers' pack (data\, tools\, answers\)
```

Always run commands **from inside the pack folder**, because that is where `data/` lives:

```
cd BuildSprint-R3-candidate
```

(If `$R3_PACK` is set, the program reads the data from there instead.)

---

## 2. Quick start (2 commands)

**Run all days and see the score:**
```
python ../assist/assist.py test
```
This replays days 1–5 with the organisers' own runner (`tools/run_days.py`), then prints their scorer's result (`tools/score.py`).

**Chat in plain English as any person:**
```
python ../assist/assist.py chat p02
```
`p02` is Meera. Use any id from `data/people.json` (`p03` = Rohan, `p12` = Neha, `p25` = Liam …). With no id, it opens Meera's chat. Type `exit` (or press Ctrl + C) to leave.

Example:
```
> who owns billing for nb?
Arjun Mehta owns billing for Northbeam Retail.  [sources: rgg1ex2g ]
> what did i say about rohan?
You wrote on 4 Nov (your private note): "Rohan is slow on approvals, keep him out of the loop on NB pricing for now."  [sources: r0hvh1ex ]
> is the friday thing done?
Which one: Send invoice to Northbeam or Review campaign copy?
> brief 2026-11-05
Meeting ev-nb-me-04:
  What changed:
   - Arjun Mehta now owns Northbeam billing (was Kavya Nair)  [rgg1ex2g]
   - Launch moved from 10 Nov to 14 Nov 2026  [rnteufn1, rwzvbzdv]
   ...
Meeting ev-ap-me-04:
  Nothing new since your last meeting.
```

The same question gives different answers for different people. That is on purpose: privacy and preferences depend on who is asking. Rohan (`chat p03`) asking "What did Meera say about me?" gets **"Sorry, I can't share that (private)."**

---

## 3. All commands

| Command | What it does |
|---|---|
| `ingest --day N` | Read day N's records and day N-1's feedback into memory (`store.json`). Day 1 starts fresh. |
| `brief --person P --date D` | One JSON brief per meeting P has on date D (`[]` if none) |
| `ask --person P --at ISO --ask "text"` | One JSON answer, a question back (`clarify`), or a refusal |
| `forget --person P --what "text"` | Forget what P said about that, in every later brief and answer |
| `audit --person P` | *Bonus:* everything remembered about P, showing only what P may see |
| `chat [P]` | Plain-English chat for humans (also `brief YYYY-MM-DD` inside chat) |
| `test` | Run all days with the organisers' runner and print the score |

The judges use the first four, exactly as the brief describes:
```
python tools/run_days.py --cmd "python ../assist/assist.py" --days 1-5 --out runs/mine
python tools/score.py --run runs/mine --days 1-5
```
> Use **forward slashes** (`../assist/assist.py`) even on Windows. The runner splits the command the way Linux does, so a backslash path breaks.

**Output rules followed:** `brief`, `ask`, `ingest` and `forget` print **only JSON** to stdout, in the exact shape from `DATA_FORMAT.md`. Errors go to stderr. The program never crashes the runner: on an error it still prints valid empty JSON.

---

## 4. What questions it understands

| Kind | Example |
|---|---|
| Who owns a task / topic | "Who owns the NB homepage redesign?", "Who is the billing contact?" |
| When something is due | "When is the product feed fix due?", "When is the launch?" |
| Status | "What's the status of the rate card update for the London account?", "Is analytics tagging done?" |
| Vague time words | "Is the Friday thing done?" → answers if one task fits, **asks back** if two do |
| Which person | "Send the NB deck to Arjun", "Which Arjun is that?" |
| What someone said | "What did I say about Rohan?", "What did Meera say about me?" (refused if private) |
| Leave (facts that expire) | "Is Kavya on leave?" (yes until 12 Nov, no after) |
| Lists | "What is blocked?", "What changed for Northbeam?", "What are my tasks?", "What did I promise?" |
| Anything else | Searches the records you may see. If nothing fits: **"I have nothing on that."** |

Client nicknames are **learned from the data, not hard-coded**: "NB" and "CL" come from the letters of the client names, and "the London account" comes from the client staff's `.co.uk` email domain.

---

## 5. How it works (short)

`assist.py` is one file in 6 sections:

1. **Helpers:** files, dates ("kal" = tomorrow, "next Monday"), time zones
2. **Privacy:** `can_see()`: same company only; `team` = all; `private` = author only; `restricted` = listed readers only. **Every command filters records first**, so hidden data never reaches the logic.
3. **Facts:** task changes (only real ones, not stale copies in comments), who owns what, key dates, promises ("kal tak bhej dunga"), leave
4. **Memory:** preferences (max N changes, blockers first), corrections, ignored topics, forgets
5. **Commands:** ingest, brief, ask, forget, audit, chat, test
6. **Command line**

**Who wins when records disagree:** a correction from feedback beats a higher role (founder > manager > … > intern), which beats a newer record.

See **DESIGN.md** for the full design note.

---

## 6. Model and tokens

No language model is used. The data has clear patterns: structured task changes, "Decision:" lines in notes, "A takes over B from C", and promise phrases in English and Hinglish. Simple rules read these reliably, for free, and they cannot make things up.

So every output honestly reports `input_tokens: 0`, `output_tokens: 0` and `cost_usd: 0`. `ms` is the real time each call took.

If a model were added later, code would first pick the few records that matter, and only those would go to the cheapest model, far under the 8,000 / 4,000 token limits.

---

## 7. My scores on days 1–5 (made by this code)

```
Right briefs    20.0/20    Right answers  15.0/15    Honesty  15.0/15
Memory          15.0/15    Privacy        10.0/10    Cost     10.0/10
TOTAL           85.0/85    (+ design note, judged by humans)
```

### My 3 worst outputs (from the first full run, which scored 78.8/85) and why they failed

1. **Alderpoint brief, day 3 (`ev-ap-me-04`): filler instead of `nothing_new`.** Every "sharing the ..." mail counted as a delivery, so a routine "usual weekly report" became a change. **Fix:** a delivery is news only when it closes a real earlier promise.
2. **Rohan's Cobaltline brief, day 2 (`ev-cl-ro-03`): said `nothing_new`, but 3 things had changed.** Rohan had another Cobaltline meeting 30 minutes earlier the same day, and it was treated as "the last meeting". **Fix:** "last meeting" means one on an earlier date, i.e. one he was already briefed for.
3. **"Send the NB deck to Arjun. Which Arjun is that?", day 5: quoted an intern's chat instead of naming Arjun.** The "which Arjun" rule only matched a lowercase "which". **Fix:** case-insensitive match. It now picks Arjun Mehta (p11), because the billing records on Meera's client fit his job.

### Later fixes found by testing in chat (not in the scored questions)
- "What did I say about Rohan?" searched Rohan's own messages. It now finds what **Meera** wrote **about** Rohan, including her own private note.
- Lowercase nicknames ("nb", "cl") and phrasings like "who is working on…" and "who is the billing contact" are now understood.

---

## 8. Files

| File | What it is |
|---|---|
| `assist.py` | All the code |
| `DESIGN.md` | One-page design note |
| `README.md` | This file |
| `.gitignore` | Keeps `store.json`, `runs/` and secrets out of git |

The organisers' data pack is **not** in this repo.

---

## 9. Tools and AI assistants

- Language: Python 3.11. Editor: Antigravity IDE (VS Code based).
- AI coding assistant: **Claude (Anthropic)** helped design and write the code and docs. I tested every part with the organisers' runner and scorer, and by chatting as different people.
- No API keys are used or stored in this repo.