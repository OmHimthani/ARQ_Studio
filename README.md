# ARQ Studio — Reliable Transmission Visualizer

An interactive web front end for the Generalized ARQ Protocol Simulator (Stop-and-Wait, Go-Back-N, Selective Repeat).

## Run
    python3 ui_backend.py            # then open http://127.0.0.1:8000   (--port N to change)
No dependencies beyond Python 3 (standard library only) and works offline. Stop with Ctrl+C.

## Original commands (unchanged)
    python3 arq_simulator.py                     # interactive CLI
    python3 arq_simulator.py --protocol gbn --frames 10 --bits 3 --sender-window 4 --lost-frames 3,7 --lost-acks 5
    python3 run_tests.py                         # regenerates execution_logs.txt, comparison_table.md, runs 4000 random checks
    python3 test_ui_backend.py                   # backend/event integration tests

## Architecture
* `arq_simulator.py` — the only place protocol decisions are made. Change: optional `observer` callback
  (`run_simulation(..., observer=fn)`). Per processed queue event it reports transmissions, ACKs, timer deadlines
  and a state snapshot. Without an observer behaviour and text logs are byte-identical to before.
* `ui_backend.py` — stdlib HTTP server: `/api/run`, `/api/compare`, `/api/parse` (rule-based natural language,
  no AI/network), `/api/scenarios` (generated from `run_tests.py`). Validation uses the engine's `validate_config`.
* `static/index.html` — all UI. Holds the immutable list of engine steps and derives every frame, ACK, timer and window from it;
  stepping back re-renders an earlier step. Playback speed only changes how fast the simulated clock is shown.

## Known limitations
* UI limited to 500 frames per run (engine has no limit; use the CLI). Timeline lists every log line (long runs scroll).
* Natural-language parser covers common phrasings; ordinals ("fourth frame") are flagged ambiguous, never guessed.
* Charts are limited to bars in the comparison table; no separate chart library.
* Prompts used during development must be added to your report by each group member (assignment requirement).
