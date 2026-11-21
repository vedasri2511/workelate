# assist: the Work Assistant That Remembers

A command-line helper that reads an agency's work data day by day. It writes meeting briefs and answers short questions. Every line cites the records it came from, and nobody sees what they are not allowed to see.

## Setup

- Python 3.9 or newer. **Nothing to install**: it uses only the standard library.
- No model and no API key. Every output reports `0` tokens and `0` cost (see "Model and tokens" below).

## How to run

Put the organisers' pack and this repo side by side:

```
Desktop\assist\                    <- this repo
Desktop\BuildSprint-R3-candidate\  <- the organisers' pack (data/, tools/, answers/)
```

Run everything **from inside the pack folder**. The program finds `data/` there, or uses `$R3_PACK` if it is set.

```
cd BuildSprint-R3-candidate

# full replay of days 1-5 with the organisers' harness, then the score
python tools/run_days.py --cmd "python ../assist/assist.py" --days 1-5 --out runs/mine
python tools/score.py --run runs/mine --days 1-5
```

Use forward slashes (`../assist/assist.py`) even on Windows: the harness splits the command like Linux does, so a backslash path breaks. On Mac/Linux, type `python3` instead of `python`.

Single commands:

```
python ../assist/assist.py ingest --day 1
python ../assist/assist.py brief  --person p02 --date 2026-11-03
python ../assist/assist.py ask    --person p02 --at 2026-11-02T18:00:00Z --ask "Who handles billing for NB?"
python ../assist/assist.py forget --person p02 --what "Forget what I said about the Dubai trip."
python ../assist/assist.py audit  --person p02        # bonus: what we remember about you
```

Memory is kept in `store.json` in the folder you run from. `ingest --day 1` always starts a fresh store.

## Files

| File | What it is |
|---|---|
| `assist.py` | All the code, in 6 numbered sections (helpers, privacy, facts, preferences, commands, CLI) |
| `DESIGN.md` | One-page design note |
| `README.md` | This file |
| `.gitignore` | Keeps `store.json`, `runs/` and secrets out of git |

## Model and tokens

No language model is used. The data follows clear patterns: task changes have structured fields; promises read like "X kal tak bhej dunga" or "Will share X by EOD"; decisions start with "Decision:"; ownership reads like "A takes over B from C". Plain rules handle these reliably, and they are free, fast and never make things up. So `usage` honestly reports 0 input tokens, 0 output tokens and $0. `ms` is the real run time of each call.

If a model were added later, the plan is: code picks the few records that matter first, and only those go to the cheapest model, staying far under the 8,000 and 4,000 token limits.

## My scores on days 1–5 (made by this code)

```
Right briefs    20.0/20    Right answers  15.0/15    Honesty  15.0/15
Memory          15.0/15    Privacy        10.0/10    Cost     10.0/10
TOTAL           85.0/85    (+ design note, judged by humans)
```

### My 3 worst outputs (from the first full run, which scored 78.8/85) and why they failed

1. **Alderpoint brief, day 3 (`ev-ap-me-04`): filler instead of `nothing_new`.** I counted every "sharing the ..." mail as a delivery, so a routine "usual weekly report" became a change. **Fix:** a delivery is news only when it closes a real earlier promise.
2. **Rohan's Cobaltline brief, day 2 (`ev-cl-ro-03`): said `nothing_new`, but 3 things had changed.** Rohan had another Cobaltline meeting 30 minutes earlier the same day, and I treated it as "the last meeting". **Fix:** "last meeting" means one on an earlier date, i.e. one he was already briefed for.
3. **"Send the NB deck to Arjun. Which Arjun is that?", day 5: quoted an intern's chat.** My "which Arjun" rule only matched a lowercase "which". **Fix:** case-insensitive match. It then picks Arjun Mehta (p11) because the billing records Meera works with fit his job.

## Tools and AI assistants

- Editor: VS Code / Antigravity IDE. Language: Python 3.11.
- AI coding assistant: Claude (Anthropic) helped design and write the code and docs. I reviewed and tested every part with the organisers' harness and scorer.
- No API keys are used or stored in this repo.
