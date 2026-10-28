#!/usr/bin/env python3
"""Integration tests for the ARQ Studio backend. Run: python3 test_ui_backend.py"""
import json, re, sys, threading, urllib.request
from http.server import ThreadingHTTPServer
import ui_backend as u

H = dict(frames=10, bits=3, lost_frames="3,7", lost_acks="5")
EXPECT = {"sw": (1, 1, 13, 3, 1, 3, 71), "gbn": (4, 1, 17, 7, 5, 2, 29), "sr": (4, 4, 13, 3, 1, 3, 27)}  # from supplied comparison_table.md
fails = []
def check(c, msg):
    if not c: fails.append(msg)

for p, (ws, wr, att, rtx, dis, tmo, tm) in EXPECT.items():
    r = u.run_one({**H, "protocol": p, "ws": ws, "wr": wr}); s = r["stats"]
    check((s["attempts"], s["retransmissions"], s["discarded"], s["timeouts"], s["sim_time"]) == (att, rtx, dis, tmo, tm), f"headline {p} stats differ")
    check(r["valid"], f"headline {p} delivery check")
    r2 = u.run_one({**H, "protocol": p, "ws": ws, "wr": wr})
    check(json.dumps(r["steps"]) == json.dumps(r2["steps"]), f"{p} not deterministic")
    # structured events agree with text log and stats
    tx = [x for st in r["steps"] for x in st["tx"]]
    check(len(tx) == s["attempts"], f"{p}: tx records != attempts")
    check(sum(x["retx"] for x in tx) == s["retransmissions"], f"{p}: retx records mismatch")
    check(sum(x["lost"] for x in tx) == s["frames_lost"] == 2, f"{p}: lost frames mismatch")
    acks = [a for st in r["steps"] for a in st["acks"]]
    check(sum(a["lost"] for a in acks) == s["acks_lost"] == 1 and len(acks) == s["acks_sent"], f"{p}: ack records mismatch")
    lost = [x for x in tx if x["lost"]]
    check(all(x["attempt"] == 1 for x in lost) and {x["frame"] for x in lost} == {3, 7}, f"{p}: loss must hit first attempt of 3 and 7")
    kinds = [st["kind"] for st in r["steps"]]
    check(kinds.count("frame_lost") == 2 and kinds.count("ack_lost") == 1 and kinds.count("timeout") >= s["timeouts"] - 0, f"{p}: loss/timeouts steps")
    check(sum(st["timed_out"] for st in r["steps"]) == s["timeouts"], f"{p}: timeout flag count")
    check(sum(len(st["delivered"]) for st in r["steps"]) == 10, f"{p}: deliveries")
    check(sum(st["discarded"] for st in r["steps"]) == s["discarded"], f"{p}: discards")
    # a lost frame is never delivered at its arrival step
    for st in r["steps"]:
        if st["kind"] == "frame_lost": check(not st["delivered"] and not st["newly_buffered"], f"{p}: lost frame was received")
    # wraparound: absolute frame 8 -> seq 0 and loss of 8 must not lose 0
    check(any(x["frame"] == 8 and x["seq"] == 0 for x in tx), f"{p}: frame 8 should carry seq 0")

# compare the supplied execution log text for the headline GBN run
logs = open("execution_logs.txt", newline="").read().replace("\r", "")
r = u.run_one({**H, "protocol": "gbn", "ws": 4, "wr": 1})
check(r["log"] in logs, "GBN headline log text not identical to execution_logs.txt")
# wrap loss semantics: lose frame 8 only
r = u.run_one(dict(protocol="gbn", frames=10, bits=3, ws=4, wr=1, lost_frames="8"))
tx = [x for st in r["steps"] for x in st["tx"] if x["lost"]]
check([(x["frame"], x["seq"]) for x in tx] == [(8, 0)], "losing frame 8 must lose only absolute frame 8")
# validation / unsafe
check(not u.run_one(dict(protocol="sr", frames=10, bits=3, ws=5, wr=5))["ok"], "SR window 5 must be rejected")
check(not u.run_one(dict(protocol="gbn", frames=10, bits=3, ws=4, wr=1, lost_frames="12"))["ok"], "out of range loss accepted")
bad = u.run_one(dict(protocol="sr", frames=6, bits=2, ws=3, wr=3, lost_acks="0,1,2", unsafe=True))
good = u.run_one(dict(protocol="sr", frames=6, bits=2, ws=2, wr=2, lost_acks="0,1,2"))
check(bad["ok"] and not bad["valid"] and good["valid"], "unsafe demo must fail, legal must pass")
cmp_ = u.compare(dict(frames=10, bits=3, ws=8, lost_frames="3", lost_acks=""))
check(cmp_["sw"]["ok"] and not cmp_["gbn"]["ok"] and not cmp_["sr"]["ok"], "compare must reject illegal Ws per protocol, not clamp")
# scenario library covers every run_tests record (45)
check(sum(len(s["runs"]) for s in u.scenarios()) == 45, "scenario library incomplete")
# NL parser
p = u.parse_text("Simulate Go-Back-N with 10 frames, 3 sequence bits, sender window 4, frame 3 and 7 lost, and ACK 5 lost.")["config"]
check(p == dict(protocol="gbn", frames="10", bits="3", ws="4", lost_frames=[3, 7], lost_acks=[5]), f"NL parse: {p}")
# HTTP round trip
srv = ThreadingHTTPServer(("127.0.0.1", 0), u.Handler); threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
req = urllib.request.Request(f"http://127.0.0.1:{port}/api/run", json.dumps({**H, "protocol": "sr", "ws": 4, "wr": 4}).encode(), {"Content-Type": "application/json"})
check(json.load(urllib.request.urlopen(req))["stats"]["sim_time"] == 27, "HTTP run")
check(b"ARQ Studio" in urllib.request.urlopen(f"http://127.0.0.1:{port}/").read(), "index served")
srv.shutdown(); srv.server_close()
print("UI backend tests:", "ALL PASSED" if not fails else "FAILED"); [print(" -", f) for f in fails]
sys.exit(1 if fails else 0)
