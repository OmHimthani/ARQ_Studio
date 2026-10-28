#!/usr/bin/env python3
"""ARQ Studio backend - serves the web UI and exposes the existing simulator as JSON.

No third-party dependencies. All protocol decisions come from arq_simulator.py; this file only
translates JSON <-> Config, collects the engine's structured step records, and parses plain English.

    python3 ui_backend.py [--port 8000]      then open http://127.0.0.1:8000
"""
import argparse, json, os, re
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from arq_simulator import (Config, PROTOCOLS, StopAndWait, GoBackN, SelectiveRepeat,
                           find_protocol, run_simulation, validate_config)

HERE = os.path.dirname(os.path.abspath(__file__))
UI_MAX_FRAMES = 500   # UI-only guard so the browser stays responsive (the engine itself has no such limit)


def _ints(v):
    if isinstance(v, str):
        v = [x for x in re.split(r"[,\s;]+", v.strip()) if x and x.lower() not in ("none", "-")]
    return {int(x) for x in v}


def build_config(d):
    cls = find_protocol(d.get("protocol"))
    if cls is None:
        raise ValueError("Unknown protocol.")
    cfg = Config(int(d["frames"]), int(d["bits"]), int(d.get("ws", 1)), int(d.get("wr", 1)),
                 _ints(d.get("lost_frames", [])), _ints(d.get("lost_acks", [])),
                 float(d.get("tf", 1)), float(d.get("tp", 2)), float(d.get("timeout", 6)))
    return cfg, cls


def run_one(d):
    """Validate then simulate. Returns a JSON-safe dict; invalid configs are rejected before any run."""
    try:
        cfg, cls = build_config(d)
    except (ValueError, KeyError, TypeError) as e:
        return dict(ok=False, errors=[f"Could not read configuration: {e}"], warnings=[])
    unsafe = bool(d.get("unsafe"))
    errors, warnings = validate_config(cfg, cls, enforce_windows=not unsafe)
    if cfg.total_frames > UI_MAX_FRAMES:
        errors.append(f"The visual simulator is limited to {UI_MAX_FRAMES} frames (use the CLI for more).")
    if min(cfg.frame_time, cfg.prop_delay, cfg.timeout) <= 0:
        errors.append("Tf, Tp and the timeout must be greater than 0.")
    effective = dict(protocol=cls.SHORT, name=cls.NAME, frames=cfg.total_frames, bits=cfg.seq_bits,
                     ws=cfg.sender_window, wr=cfg.receiver_window, lost_frames=sorted(cfg.lost_frames),
                     lost_acks=sorted(cfg.lost_acks), tf=cfg.frame_time, tp=cfg.prop_delay,
                     timeout=cfg.timeout, unsafe=unsafe)
    if errors:
        return dict(ok=False, errors=errors, warnings=warnings, config=effective)
    if d.get("validate_only"):
        return dict(ok=True, errors=[], warnings=warnings, config=effective)
    steps = []
    stats, lines = run_simulation(cfg, cls, echo=False, observer=steps.append)
    for i, s in enumerate(steps):          # exact log lines the engine wrote while producing each step
        s["id"] = i
        s["logs"] = [l for l in lines[s.pop("log_from"):s.pop("log_to")] if l.startswith("[t=") or s["kind"] == "done"]
    ok = stats.completed and stats.in_order_ok and stats.delivered == cfg.total_frames
    return dict(ok=True, warnings=warnings, config=effective, stats=asdict(stats), valid=ok,
                steps=steps, log="\n".join(lines))


def compare(d):
    base = dict(d)
    res = {}
    ws = int(d.get("ws", 4))
    for cls, (a, b) in ((StopAndWait, (1, 1)), (GoBackN, (ws, 1)), (SelectiveRepeat, (ws, ws))):
        res[cls.SHORT] = run_one({**base, "protocol": cls.SHORT, "ws": a, "wr": b, "unsafe": False})
    return res


_scen = None


def scenarios():
    """Scenario library generated from the existing run_tests.py (same configs as the assignment tests)."""
    global _scen
    if _scen is None:
        import run_tests
        run_tests.sections.clear(); run_tests.records.clear()
        run_tests.build_scenarios()
        _scen = []
        for title, desc, recs in run_tests.sections:
            runs = []
            for r in recs:
                c = r["cfg"]
                runs.append(dict(protocol=r["cls"].SHORT, name=r["cls"].NAME, frames=c.total_frames,
                                 bits=c.seq_bits, ws=c.sender_window, wr=c.receiver_window,
                                 lost_frames=sorted(c.lost_frames), lost_acks=sorted(c.lost_acks),
                                 tf=c.frame_time, tp=c.prop_delay, timeout=c.timeout, note=r["note"],
                                 unsafe=r["note"].startswith("UNSAFE")))
            _scen.append(dict(title=title, desc=desc, runs=runs))
    return _scen


# --------------------------------------------------------------------------- #
# Deterministic natural-language parser (no AI, no network)
# --------------------------------------------------------------------------- #
ORD = r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th))\b"
LST = r"((?:\d+|\s|,|and|&|frames?|acks?)+?)"
LOSS = r"\s*(?:are\s+|is\s+|to be\s+|should be\s+|get\s+|gets\s+)*(?:lost|dropped)"


def parse_text(text):
    t, cfg, notes, amb = text.lower(), {}, [], []
    if re.search(r"stop[\s-]*and[\s-]*wait|\bsaw\b|\bsw\b|s&w", t): cfg["protocol"] = "sw"
    elif re.search(r"go[\s-]*back[\s-]*n|\bgbn\b", t): cfg["protocol"] = "gbn"
    elif re.search(r"selective[\s-]*repeat|\bsr\b", t): cfg["protocol"] = "sr"
    else: amb.append("No protocol recognised (Stop-and-Wait, Go-Back-N or Selective Repeat).")
    for key, pat in (("frames", r"(\d+)\s*(?:data\s+)?frames\b(?!\s*\d)"), ("bits", r"(\d+)\s*(?:sequence\s*)?bits?\b|\bm\s*=\s*(\d+)"),
                     ("ws", r"sender\s+window(?:\s+size)?(?:\s+of|\s+is|\s*=|\s*:)?\s*(\d+)"),
                     ("wr", r"receiver\s+window(?:\s+size)?(?:\s+of|\s+is|\s*=|\s*:)?\s*(\d+)"),
                     ("tf", r"\btf\s*=?\s*(\d+(?:\.\d+)?)"), ("tp", r"\btp\s*=?\s*(\d+(?:\.\d+)?)|propagation(?:\s+delay)?(?:\s+of|\s+is|\s*=)?\s*(\d+(?:\.\d+)?)"),
                     ("timeout", r"timeout(?:\s+of|\s+is|\s*=)?\s*(\d+(?:\.\d+)?)")):
        m = re.search(pat, t)
        if m: cfg[key] = next(g for g in m.groups() if g)
    if "ws" not in cfg:
        m = re.search(r"(?<!receiver )window(?:\s+size)?(?:\s+of|\s+is|\s*=)?\s*(\d+)", t)
        if m:
            cfg["ws"] = m.group(1)
            notes.append("'window N' was read as the sender window.")
    for key, word in (("lost_frames", r"(?<!ack )(?<!ack)frames?"), ("lost_acks", r"acks?")):
        nums = set()
        for m in re.finditer(word + r"\s*(?:numbers?\s*)?" + LST + LOSS, t):
            nums |= {int(x) for x in re.findall(r"\d+", m.group(1))}
        if nums: cfg[key] = sorted(nums)
    for m in re.finditer(ORD, re.sub(r"first (?:transmission|attempt)", "", t)):
        amb.append(f"'{m.group(1)}' is ordinal wording - the engine numbers frames from 0, so I did not guess "
                   f"which frame you mean. Enter the absolute frame number instead.")
    if re.search(r"first transmission|first attempt", t):
        notes.append("Losses always hit the first transmission only (engine rule).")
    if cfg.get("protocol") == "sw" and ("ws" in cfg or "wr" in cfg):
        notes.append("Stop-and-Wait windows are fixed at 1; the window value was ignored.")
        cfg.pop("ws", None); cfg.pop("wr", None)
    notes.append("Frame / ACK numbers are absolute indices starting at 0.")
    return dict(config=cfg, notes=notes, ambiguities=amb)


# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "static", "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if self.path == "/api/scenarios":
            return self._send(200, scenarios())
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            fn = {"/api/run": run_one, "/api/compare": compare, "/api/parse": lambda x: parse_text(x.get("text", ""))}.get(self.path)
            if not fn: return self._send(404, {"error": "not found"})
            self._send(200, fn(d))
        except Exception as e:  # never crash the server on bad input
            self._send(400, {"ok": False, "errors": [f"Bad request: {e}"], "warnings": []})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    port = ap.parse_args().port
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"ARQ Studio running at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
