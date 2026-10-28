#!/usr/bin/env python3
"""
Test runner for the generalized ARQ simulator.

Runs the seven test conditions required by the assignment on all three protocols,
writes the complete execution logs to   execution_logs.txt
and the comparison tables to            comparison_table.md
then runs a randomized consistency check (every legal configuration must deliver
all frames exactly once and in order).

Usage:  python3 run_tests.py
"""

import random
import sys

from arq_simulator import (Config, StopAndWait, GoBackN, SelectiveRepeat,
                           run_simulation, validate_config)

SW, GBN, SR = StopAndWait, GoBackN, SelectiveRepeat
N = 10          # frames in the standard scenarios
M = 3           # sequence bits in the standard scenarios (sequence numbers 0..7)

records = []    # one entry per simulation, in execution order
sections = []   # (section title, description, [records or rejected-config dicts])


def make_cfg(frames=N, bits=M, ws=1, wr=1, lost_frames=(), lost_acks=()):
    return Config(frames, bits, ws, wr, set(lost_frames), set(lost_acks))


def simulate(test, cls, cfg, enforce=True, note=""):
    """Run one simulation (or record a rejection) and remember the result."""
    errors, warnings = validate_config(cfg, cls, enforce_windows=enforce)
    if errors:
        rec = dict(test=test, cls=cls, cfg=cfg, rejected=True, errors=errors, note=note)
    else:
        stats, lines = run_simulation(cfg, cls, echo=False)
        rec = dict(test=test, cls=cls, cfg=cfg, rejected=False, stats=stats, lines=lines,
                   warnings=warnings, note=note)
    records.append(rec)
    return rec


def trio(test, window, lost_frames=(), lost_acks=(), bits=M, frames=N):
    """Stop-and-Wait, Go-Back-N and Selective Repeat under the same channel conditions."""
    return [
        simulate(test, SW, make_cfg(frames, bits, 1, 1, lost_frames, lost_acks)),
        simulate(test, GBN, make_cfg(frames, bits, window, 1, lost_frames, lost_acks)),
        simulate(test, SR, make_cfg(frames, bits, window, window, lost_frames, lost_acks)),
    ]


def describe(cfg):
    return (f"frames={cfg.total_frames}, m={cfg.seq_bits}, Ws={cfg.sender_window}, Wr={cfg.receiver_window}, "
            f"lost frames={sorted(cfg.lost_frames) or '-'}, lost ACKs={sorted(cfg.lost_acks) or '-'}")


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #
def build_scenarios():
    s = sections

    s.append(("Headline scenario (the assignment's sample input)",
              f"{N} frames, m = 3, window 4, frames 3 and 7 lost, ACK 5 lost - all three protocol selections.",
              trio("Headline", 4, lost_frames=(3, 7), lost_acks=(5,))))

    s.append(("Test 1 - No frame or ACK loss",
              "Baseline: shows the throughput benefit of pipelining (window 4 for GBN and SR).",
              trio("Test 1", 4)))

    s.append(("Test 2 - One data frame lost",
              "Frame 3 is lost on its first transmission.",
              trio("Test 2", 4, lost_frames=(3,))))

    s.append(("Test 3a - One ACK lost",
              "ACK 5 is lost. GBN's cumulative ACK 6 makes up for it; SR and Stop-and-Wait must time out.",
              trio("Test 3a", 4, lost_acks=(5,))))

    s.append(("Test 3b - The last ACK lost",
              "ACK 9 is lost and no later ACK can cover it, so every protocol must time out and retransmit.",
              trio("Test 3b", 4, lost_acks=(9,))))

    s.append(("Test 4 - Multiple consecutive data frames lost",
              "Frames 3, 4 and 5 are lost one after another.",
              trio("Test 4", 4, lost_frames=(3, 4, 5))))

    t5 = [simulate("Test 5", SW, make_cfg(N, M, 1, 1, (3, 7)))]
    t5 += [simulate("Test 5", GBN, make_cfg(N, M, w, 1, (3, 7))) for w in (1, 2, 4, 7)]
    t5 += [simulate("Test 5", SR, make_cfg(N, M, w, w, (3, 7))) for w in (1, 2, 4)]
    t5.append(simulate("Test 5", SR, make_cfg(N, M, 4, 2, (3, 7)),
                       note="Wr < Ws: frames beyond the receiver window are discarded and resent"))
    s.append(("Test 5 - Different sender window sizes for GBN and SR",
              "Frames 3 and 7 lost, m = 3. GBN windows 1, 2, 4, 7 (max 2^m - 1 = 7); SR windows 1, 2, 4 "
              "(max 2^(m-1) = 4); Stop-and-Wait shown for reference. The last row uses a receiver window "
              "smaller than the sender window.", t5))

    t6 = []
    for bits in (1, 2, 3, 4):
        space = 2 ** bits
        t6.append(simulate("Test 6", GBN, make_cfg(N, bits, space - 1, 1, (3, 7)),
                           note=f"m={bits}, largest legal GBN window"))
        t6.append(simulate("Test 6", SR, make_cfg(N, bits, space // 2, space // 2, (3, 7)),
                           note=f"m={bits}, largest legal SR window"))
    s.append(("Test 6 - Different sequence number bit lengths",
              "Frames 3 and 7 lost. For m = 1..4 each protocol uses the largest window its sequence space "
              "allows: the number of bits caps the window, and therefore the throughput.", t6))

    t7 = [
        simulate("Test 7", SR, make_cfg(N, 3, 5, 5), note="SR window 5 > 2^(m-1) = 4"),
        simulate("Test 7", SR, make_cfg(N, 3, 4, 5), note="SR receiver window 5 > 2^(m-1) = 4"),
        simulate("Test 7", GBN, make_cfg(N, 3, 8, 1), note="GBN window 8 > 2^m - 1 = 7"),
        simulate("Test 7", GBN, make_cfg(N, 3, 4, 2), note="GBN receiver window must be 1"),
        simulate("Test 7", SW, make_cfg(N, 3, 2, 1), note="Stop-and-Wait window must be 1"),
        simulate("Test 7", SR, make_cfg(0, 3, 2, 2), note="zero frames"),
        simulate("Test 7", GBN, make_cfg(N, 0, 1, 1), note="zero sequence bits"),
        simulate("Test 7", GBN, make_cfg(N, 3, 4, 1, (12,), (15,)), note="lost frame / ACK numbers out of range"),
    ]
    s.append(("Test 7 - Invalid configurations",
              "The simulator must reject each of these before any transmission starts.", t7))

    t7b = [
        simulate("Test 7b", SR, make_cfg(6, 2, 3, 3, (), (0, 1, 2)), enforce=False,
                 note="UNSAFE: m=2, SR window 3 > 2^(m-1) = 2, window check bypassed with --unsafe"),
        simulate("Test 7b", SR, make_cfg(6, 2, 2, 2, (), (0, 1, 2)),
                 note="same channel errors with the legal window 2 = 2^(m-1)"),
    ]
    s.append(("Test 7b - Why the window must be limited (demonstration)",
              "With m = 2 and ACKs 0-2 lost, an oversized SR window makes the receiver accept an old "
              "retransmission as a brand-new frame (sequence-number ambiguity). The legal window does not.", t7b))


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def row_for(rec):
    cfg = rec["cfg"]
    name = rec["cls"].NAME
    if rec["rejected"]:
        return None
    st = rec["stats"]
    ok = st.completed and st.in_order_ok and st.delivered == cfg.total_frames
    delivered = f"{st.delivered}/{cfg.total_frames}" + ("" if ok else " (FAILED)")
    extra = ""
    if rec["cls"] is not SW:
        extra = f" (m={cfg.seq_bits})" if rec["test"] == "Test 6" else ""
    return (f"| {name} | {cfg.sender_window} / {cfg.receiver_window}{extra} | {delivered} | {st.attempts} | "
            f"{st.retransmissions} | {st.discarded} | {st.timeouts} | {st.sim_time:g} |")


def write_reports():
    with open("execution_logs.txt", "w") as lf:
        lf.write("EXECUTION LOGS - Generalized ARQ Protocol Simulator\n")
        lf.write("=" * 60 + "\n")
        lf.write("Time units: frame transmission = 1, one-way propagation = 2, timeout = 6.\n")
        lf.write("Lost frames/ACKs are lost on their first transmission only.\n\n")
        lf.write("Contents\n--------\n")
        for title, _, _ in sections:
            lf.write(f"  {title}\n")
        lf.write("\n")
        for title, desc, recs in sections:
            lf.write("\n" + "#" * 78 + "\n")
            lf.write(f"# {title}\n# {desc}\n")
            lf.write("#" * 78 + "\n")
            for rec in recs:
                lf.write("\n" + "-" * 78 + "\n")
                lf.write(f"{rec['test']} | {rec['cls'].NAME} | {describe(rec['cfg'])}\n")
                if rec["note"]:
                    lf.write(f"Note: {rec['note']}\n")
                lf.write("-" * 78 + "\n")
                if rec["rejected"]:
                    lf.write("INVALID CONFIGURATION - simulation not started:\n")
                    for e in rec["errors"]:
                        lf.write(f"  - {e}\n")
                else:
                    for w in rec["warnings"]:
                        lf.write(f"Warning: {w}\n")
                    lf.write("\n".join(rec["lines"]) + "\n")

    with open("comparison_table.md", "w") as tf:
        tf.write("# Comparison tables\n\n")
        tf.write("Time units: frame transmission = 1, one-way propagation = 2, timeout = 6 "
                 "(ACK round trip = 4). Each lost frame/ACK is lost on its first transmission only. "
                 "Ws / Wr are the sender / receiver window sizes. \"Discarded\" counts frames that reached "
                 "the receiver but were not accepted (out of order in GBN, duplicates in all protocols).\n\n")
        for title, desc, recs in sections:
            tf.write(f"## {title}\n\n{desc}\n\n")
            valid = [r for r in recs if not r["rejected"]]
            if valid:
                tf.write("| Protocol | Ws / Wr | Delivered | Transmission attempts | Retransmissions | "
                         "Discarded | Timeouts | Simulated time |\n")
                tf.write("|---|---|---|---|---|---|---|---|\n")
                for r in valid:
                    tf.write(row_for(r) + "\n")
                tf.write("\n")
                notes = [f"- {r['cls'].NAME} (Ws={r['cfg'].sender_window}, Wr={r['cfg'].receiver_window}"
                         f", m={r['cfg'].seq_bits}): {r['note']}" for r in valid if r["note"]]
                if notes and title.startswith(("Test 5", "Test 7b")):
                    tf.write("\n".join(notes) + "\n\n")
            rej = [r for r in recs if r["rejected"]]
            if rej:
                tf.write("| Protocol | Configuration tried | Result |\n|---|---|---|\n")
                for r in rej:
                    msg = " ".join(r["errors"])
                    tf.write(f"| {r['cls'].NAME} | {r['note']} | REJECTED: {msg} |\n")
                tf.write("\n")


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def lookup(test, cls, ws=None, wr=None, bits=None):
    for r in records:
        if r["test"] == test and r["cls"] is cls and not r["rejected"]:
            c = r["cfg"]
            if (ws is None or c.sender_window == ws) and (wr is None or c.receiver_window == wr) \
                    and (bits is None or c.seq_bits == bits):
                return r["stats"]
    raise KeyError((test, cls, ws, wr, bits))


def check_results():
    problems = []
    for r in records:
        if r["rejected"] or r["test"] == "Test 7b" and r["cfg"].sender_window == 3:
            continue
        st, c = r["stats"], r["cfg"]
        if not (st.completed and st.in_order_ok and st.delivered == c.total_frames):
            problems.append(f"delivery check failed: {r['test']} {r['cls'].NAME} {describe(c)}")
        if st.attempts != c.total_frames + st.retransmissions:
            problems.append(f"attempt bookkeeping wrong: {r['test']} {r['cls'].NAME}")
    # hand-calculated expectations for the no-loss run (Tf=1, Tp=2):
    #   Stop-and-Wait: 10 frames * (1 + 2 + 2) = 50
    #   window 4: frame k >= 4 starts when ACK k-4 arrives, i.e. s_k = s_(k-4) + 5, so frame 9 starts
    #   at 11 and its ACK is back at 11 + 1 + 2 + 2 = 16
    for cls, expected in ((SW, 50), (GBN, 16), (SR, 16)):
        got = lookup("Test 1", cls).sim_time
        if got != expected or lookup("Test 1", cls).retransmissions != 0:
            problems.append(f"Test 1 {cls.NAME}: simulated time {got}, expected {expected}")
    # GBN with window 1 behaves like Stop-and-Wait
    a, b = lookup("Test 5", SW), lookup("Test 5", GBN, ws=1)
    if (a.attempts, a.retransmissions, a.sim_time) != (b.attempts, b.retransmissions, b.sim_time):
        problems.append("GBN window 1 does not match Stop-and-Wait")
    # SR with window 1 behaves like Stop-and-Wait too
    c1 = lookup("Test 5", SR, ws=1, wr=1)
    if (a.attempts, a.retransmissions, a.sim_time) != (c1.attempts, c1.retransmissions, c1.sim_time):
        problems.append("SR window 1 does not match Stop-and-Wait")
    # the unsafe demonstration must actually go wrong, and the legal one must not
    bad = [r for r in records if r["test"] == "Test 7b"]
    if not bad[0]["rejected"] and bad[0]["stats"].in_order_ok and \
            bad[0]["stats"].delivered == bad[0]["cfg"].total_frames:
        problems.append("unsafe window demonstration did not show a failure")
    ok = bad[1]["stats"]
    if not (ok.completed and ok.in_order_ok):
        problems.append("legal-window counterpart of the demonstration failed")
    # every Test 7 configuration must be rejected
    for r in records:
        if r["test"] == "Test 7" and not r["rejected"]:
            problems.append(f"invalid configuration was accepted: {r['note']}")
    return problems


def fuzz(runs=4000, seed=2026):
    """Random legal configurations: every one must deliver all frames once, in order."""
    rng = random.Random(seed)
    failures = []
    for i in range(runs):
        cls = rng.choice([SW, GBN, SR])
        n = rng.randint(1, 30)
        bits = rng.randint(1, 5)
        space = 2 ** bits
        if cls is SW:
            ws = wr = 1
        elif cls is GBN:
            ws, wr = rng.randint(1, space - 1), 1
        else:
            ws, wr = rng.randint(1, space // 2), rng.randint(1, space // 2)
        lf = {x for x in range(n) if rng.random() < 0.3}
        la = {x for x in range(n) if rng.random() < 0.3}
        cfg = Config(n, bits, ws, wr, lf, la)
        errors, _ = validate_config(cfg, cls)
        assert not errors, errors
        st, _ = run_simulation(cfg, cls, echo=False)
        if not (st.completed and st.in_order_ok and st.delivered == n
                and st.attempts == n + st.retransmissions and st.frames_lost == len(lf)):
            failures.append((cls.NAME, describe(cfg)))
    return runs, failures


def main():
    build_scenarios()
    write_reports()
    print(f"Ran {len(records)} scenarios; wrote execution_logs.txt and comparison_table.md")
    problems = check_results()
    runs, failures = fuzz()
    print(f"Random consistency check: {runs - len(failures)}/{runs} legal configurations passed")
    for p in problems + [f"fuzz failure: {f}" for f in failures[:10]]:
        print("PROBLEM:", p)
    return 1 if problems or failures else 0


if __name__ == "__main__":
    sys.exit(main())
