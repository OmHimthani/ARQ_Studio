#!/usr/bin/env python3
"""
Generalized ARQ Protocol Simulator
==================================
One program that can run Stop-and-Wait, Go-Back-N (GBN) or Selective Repeat (SR)
over a simulated unreliable channel. The protocol is chosen at runtime.

Design
------
* ARQProtocol (abstract base class) owns everything the protocols have in common:
  the simulated clock, the event queue, the channel (frame / ACK loss), timers,
  frame transmission, statistics and logging.
* StopAndWait, GoBackN and SelectiveRepeat are subclasses. Each one only supplies
  the protocol-specific behaviour:
      - sender_on_ack()      how the sender reacts to an ACK
      - on_timeout()         what is retransmitted when a timer expires
      - receiver_on_frame()  frame acceptance / ordering / buffering / ACK rules
      - on_transmitted()     which timer(s) are started when a frame is sent
      - check_windows()      legal window sizes for the chosen sequence-number space
* PROTOCOLS (registry) is the only place the menu and the CLI look at, so adding a
  new ARQ protocol = write one new subclass + add it to PROTOCOLS.

Simulation model (all times are in abstract "time units")
---------------------------------------------------------
* The sender pushes one data frame onto the channel at a time (Tf = frame_time).
* A frame needs Tp = prop_delay to reach the receiver; an ACK needs Tp to come back
  (ACK transmission time is treated as 0).
* A retransmission timer for a frame starts when its transmission ends and expires
  after `timeout` time units (it must exceed the ACK round trip 2*Tp).
* Frames/ACKs listed as lost are lost on their FIRST transmission only, so every
  retransmission gets through and the simulation always terminates.
* Frame and ACK numbers used for loss configuration are absolute (0 .. N-1). On the
  wire, sequence numbers are taken modulo 2^m and both sender and receiver decide
  using modulo arithmetic only, so the sequence-space/window-size rules really matter.

Usage
-----
    python3 arq_simulator.py                       # interactive menu
    python3 arq_simulator.py --protocol gbn --frames 10 --bits 3 \
            --sender-window 4 --lost-frames 3,7 --lost-acks 5
"""

import argparse
import heapq
import itertools
import sys
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field

MAX_EVENTS = 200_000  # safety guard against runaway simulations (e.g. unsafe configs)


# --------------------------------------------------------------------------- #
# Configuration and statistics
# --------------------------------------------------------------------------- #
@dataclass
class Config:
    total_frames: int
    seq_bits: int
    sender_window: int = 1
    receiver_window: int = 1
    lost_frames: set = field(default_factory=set)
    lost_acks: set = field(default_factory=set)
    frame_time: float = 1.0   # Tf  : time to put one frame on the channel
    prop_delay: float = 2.0   # Tp  : one-way propagation delay
    timeout: float = 6.0      # retransmission timeout (from end of frame transmission)


@dataclass
class Stats:
    attempts: int = 0           # every data-frame transmission, including retransmissions
    retransmissions: int = 0    # transmissions beyond the first for a frame
    delivered: int = 0          # frames handed to the upper layer by the receiver
    discarded: int = 0          # frames that reached the receiver but were not accepted
    frames_lost: int = 0        # data frames lost in the channel
    acks_sent: int = 0
    acks_lost: int = 0
    timeouts: int = 0
    sim_time: float = 0.0       # time at which the sender received the final ACK
    completed: bool = False     # sender finished (all frames acknowledged)
    in_order_ok: bool = True    # receiver delivered the right frames in the right order


# --------------------------------------------------------------------------- #
# Common interface + shared machinery
# --------------------------------------------------------------------------- #
class ARQProtocol(ABC):
    NAME = "Abstract ARQ"
    SHORT = "abstract"
    ASK_SENDER_WINDOW = True      # does the menu ask for a sender window size?
    ASK_RECEIVER_WINDOW = False   # does the menu ask for a receiver window size?

    def __init__(self, cfg, log=print, observer=None):
        self.cfg = cfg
        self.log = log
        self.observer = observer          # optional callback(step_record) for the visual front end
        self._tx, self._acks = [], []     # transmissions / ACKs created during the current step
        self.timer_due = {}               # frame -> time its live timer expires
        self.N = cfg.total_frames
        self.M = 2 ** cfg.seq_bits            # size of the sequence-number space
        self.Ws = cfg.sender_window
        self.Wr = cfg.receiver_window
        self.now = 0.0
        self.stats = Stats()
        self._events = []
        self._counter = itertools.count()

        # sender state (absolute frame indices)
        self.base = 0                         # oldest unacknowledged frame
        self.next_new = 0                     # next frame the sender will transmit
        self.sent_hi = 0                      # 1 + highest frame ever transmitted
        self.busy_until = 0.0                 # sender is busy putting a frame on the wire
        self.attempts = [0] * self.N
        self.last_tx_end = [0.0] * self.N
        self.acked = [False] * self.N
        self.retx_queue = deque()
        self.timers = {}                      # frame -> generation of its live timer

        # channel state: losses are consumed on first use
        self._frame_losses = set(cfg.lost_frames)
        self._ack_losses = set(cfg.lost_acks)

    # ----- class-level hooks ------------------------------------------------ #
    @classmethod
    @abstractmethod
    def check_windows(cls, cfg):
        """Return a list of error strings if the window sizes are illegal for this protocol."""

    # ----- logging / event plumbing ---------------------------------------- #
    def say(self, who, msg):
        self.log(f"[t={self.now:6.2f}] {who:<8}: {msg}")

    def schedule(self, at, kind, *payload):
        heapq.heappush(self._events, (at, next(self._counter), kind, payload))

    def start_timer(self, frame, deadline):
        gen = next(self._counter)
        self.timers[frame] = gen
        self.timer_due[frame] = max(deadline, self.now)
        self.schedule(max(deadline, self.now), "timeout", frame, gen)

    def stop_timer(self, frame):
        self.timers.pop(frame, None)
        self.timer_due.pop(frame, None)

    # ----- main loop -------------------------------------------------------- #
    def run(self):
        pre0 = self._probe() if self.observer else None
        self._print_header()
        self.kick()
        self._observe("start", (), pre0)
        steps = 0
        while self.base < self.N:
            if not self._events:
                self.say("Simulator", "No pending events but transmission is incomplete - stopping.")
                break
            steps += 1
            if steps > MAX_EVENTS:
                self.say("Simulator", "Event limit reached - simulation aborted.")
                break
            at, _, kind, payload = heapq.heappop(self._events)
            self.now = at
            pre = self._probe() if self.observer else None
            if kind == "frame":
                self.receiver_on_frame(*payload)
            elif kind == "frame_lost":
                self.say("Channel", f"Frame {payload[0]} LOST in transit (never reaches the receiver)")
            elif kind == "ack":
                self.sender_on_ack(*payload)
            elif kind == "ack_lost":
                self.say("Channel", f"ACK {payload[0]} LOST in transit (never reaches the sender)")
            elif kind == "timeout":
                frame, gen = payload
                if self.timers.get(frame) == gen:
                    del self.timers[frame]
                    self.timer_due.pop(frame, None)
                    self.stats.timeouts += 1
                    self.on_timeout(frame)
            # kind == "kick" needs no handler of its own
            self.kick()
            self._observe(kind, payload, pre)
        pre_done = self._probe() if self.observer else None
        self.stats.sim_time = self.now
        self.stats.completed = self.base >= self.N
        if self.stats.completed:
            self.say("Sender", f"All {self.N} frames acknowledged - transmission complete")
        self._print_summary()
        self._observe("done", (), pre_done)
        return self.stats

    # ----- sender side (shared) -------------------------------------------- #
    def kick(self):
        """If the sender is idle and has something it may send, transmit it."""
        if self.now < self.busy_until:
            return
        frame = self.pick_next()
        if frame is not None:
            self.transmit(frame)

    def pick_next(self):
        """Retransmissions first, then new frames while the sender window allows."""
        while self.retx_queue:
            f = self.retx_queue.popleft()
            if f >= self.base and not self.acked[f]:
                return f
        if self.next_new < self.N and self.next_new < self.base + self.Ws:
            f = self.next_new
            self.next_new += 1
            return f
        return None

    def transmit(self, frame):
        seq = frame % self.M
        is_retx = self.attempts[frame] > 0
        self.attempts[frame] += 1
        self.stats.attempts += 1
        if is_retx:
            self.stats.retransmissions += 1
        tx_end = self.now + self.cfg.frame_time
        self.busy_until = tx_end
        self.last_tx_end[frame] = tx_end
        self.sent_hi = max(self.sent_hi, frame + 1)
        how = f"retransmitted (attempt {self.attempts[frame]})" if is_retx else "transmitted"
        self.say("Sender", f"Frame {frame} (seq {seq}) {how}")
        self.on_transmitted(frame, tx_end)
        arrive = tx_end + self.cfg.prop_delay
        self._tx.append(dict(frame=frame, seq=seq, attempt=self.attempts[frame], retx=is_retx, start=self.now,
                             end=tx_end, arrive=arrive, lost=frame in self._frame_losses))
        if frame in self._frame_losses:
            self._frame_losses.discard(frame)
            self.stats.frames_lost += 1
            self.schedule(arrive, "frame_lost", frame)
        else:
            self.schedule(arrive, "frame", frame, seq)
        self.schedule(tx_end, "kick")

    # ----- receiver side (shared helpers) ---------------------------------- #
    def deliver(self, frame):
        """Hand a frame to the upper layer and check that it is the right one."""
        expected = self.stats.delivered
        if frame != expected:
            self.stats.in_order_ok = False
            self.say("Receiver", f"!! ERROR: delivered frame {frame} but frame {expected} was expected "
                                 f"(sequence-number ambiguity)")
        self.stats.delivered += 1

    def send_ack(self, label, seq, note=""):
        """Generate an ACK. `label` is the absolute frame number used for loss configuration."""
        self.stats.acks_sent += 1
        extra = f" ({note})" if note else ""
        self.say("Receiver", f"ACK {label} (seq {seq}) generated{extra}")
        arrive = self.now + self.cfg.prop_delay
        self._acks.append(dict(label=label, seq=seq, send=self.now, arrive=arrive, note=note,
                               lost=label in self._ack_losses))
        if label in self._ack_losses:
            self._ack_losses.discard(label)
            self.stats.acks_lost += 1
            self.schedule(arrive, "ack_lost", label)
        else:
            self.schedule(arrive, "ack", label, seq)

    # ----- protocol-specific behaviour (implemented by subclasses) --------- #
    @abstractmethod
    def on_transmitted(self, frame, tx_end):
        """Called after a frame is put on the wire: start the protocol's timer(s)."""

    @abstractmethod
    def sender_on_ack(self, label, seq):
        """An ACK reaches the sender."""

    @abstractmethod
    def on_timeout(self, frame):
        """A retransmission timer expired."""

    @abstractmethod
    def receiver_on_frame(self, frame, seq):
        """A data frame reaches the receiver."""

    # ----- structured events for visualisation (no protocol decisions are made here) ---- #
    def _probe(self):
        return dict(delivered=self.stats.delivered, discarded=self.stats.discarded, base=self.base,
                    acked={i for i in range(self.base, self.sent_hi) if self.acked[i]},
                    buffered=set(getattr(self, "rbuf", {}).values()), timeouts=self.stats.timeouts,
                    log_len=getattr(self, "_log_len", lambda: 0)())

    def _observe(self, kind, payload, pre=None):
        if not self.observer:
            return
        pre = pre or self._probe()
        post = self._probe()
        rbuf = sorted(getattr(self, "rbuf", {}).values())
        rec = dict(
            t=self.now, kind=kind, payload=list(payload), log_from=pre["log_len"], log_to=post["log_len"],
            tx=self._tx, acks=self._acks,
            delivered=list(range(pre["delivered"], post["delivered"])),
            newly_buffered=sorted(post["buffered"] - pre["buffered"]),
            discarded=post["discarded"] - pre["discarded"],
            newly_acked=sorted(post["acked"] - pre["acked"] | {i for i in range(pre["base"], post["base"])
                                                              if i not in pre["acked"] and self.acked[i]}),
            timed_out=post["timeouts"] > pre["timeouts"],
            snap=dict(base=self.base, next_new=self.next_new, sent_hi=self.sent_hi,
                      acked=sorted(post["acked"]), timers={str(k): v for k, v in sorted(self.timer_due.items())},
                      delivered=self.stats.delivered, buffered=rbuf,
                      expected_seq=self.stats.delivered % self.M),
        )
        self._tx, self._acks = [], []
        self.observer(rec)

    # ----- reporting -------------------------------------------------------- #
    def _print_header(self):
        c = self.cfg
        self.log("========== TRANSMISSION LOG ==========")
        self.log(f"Protocol: {self.NAME}")
        self.log(f"Frames: {self.N} | sequence bits: {c.seq_bits} (sequence numbers 0..{self.M - 1}) | "
                 f"sender window: {self.Ws} | receiver window: {self.Wr}")
        self.log(f"Timing (time units): frame transmission = {c.frame_time:g}, one-way propagation = "
                 f"{c.prop_delay:g}, timeout = {c.timeout:g} (counted from end of frame transmission)")
        self.log(f"Channel errors: lost frames = {sorted(c.lost_frames) or 'none'}, "
                 f"lost ACKs = {sorted(c.lost_acks) or 'none'} (each loss hits the first transmission only)")
        self.log("")

    def _print_summary(self):
        s = self.stats
        ok = s.completed and s.in_order_ok and s.delivered == self.N
        self.log("")
        self.log("========== PERFORMANCE SUMMARY ==========")
        self.log(f"Protocol                      : {self.NAME}")
        self.log(f"Successfully delivered frames : {s.delivered} / {self.N}")
        self.log(f"Total transmission attempts   : {s.attempts}")
        self.log(f"Total retransmissions         : {s.retransmissions}")
        self.log(f"Total frames discarded        : {s.discarded}")
        self.log(f"Data frames lost in channel   : {s.frames_lost}")
        self.log(f"ACKs generated / lost         : {s.acks_sent} / {s.acks_lost}")
        self.log(f"Timeouts                      : {s.timeouts}")
        self.log(f"Total simulated time          : {s.sim_time:g} time units")
        self.log(f"Delivery check                : {'PASSED (all frames delivered once, in order)' if ok else 'FAILED'}")


# --------------------------------------------------------------------------- #
# Stop-and-Wait
# --------------------------------------------------------------------------- #
class StopAndWait(ARQProtocol):
    NAME = "Stop-and-Wait"
    SHORT = "sw"
    ASK_SENDER_WINDOW = False
    ASK_RECEIVER_WINDOW = False

    def __init__(self, cfg, log=print, observer=None):
        super().__init__(cfg, log, observer)
        self.expected_seq = 0                 # receiver: sequence number it wants next
        self.rcv_next = 0                     # receiver: absolute number of next frame (log only)

    @classmethod
    def check_windows(cls, cfg):
        errs = []
        if cfg.sender_window != 1:
            errs.append(f"Stop-and-Wait requires a sender window of 1 (got {cfg.sender_window}).")
        if cfg.receiver_window != 1:
            errs.append(f"Stop-and-Wait requires a receiver window of 1 (got {cfg.receiver_window}).")
        return errs

    def on_transmitted(self, frame, tx_end):
        self.start_timer(frame, tx_end + self.cfg.timeout)

    def sender_on_ack(self, label, seq):
        if self.base < self.sent_hi and seq == self.base % self.M:
            self.say("Sender", f"ACK {label} received -> frame {self.base} acknowledged")
            self.stop_timer(self.base)
            self.acked[self.base] = True
            self.base += 1
            self.next_new = max(self.next_new, self.base)
        else:
            self.say("Sender", f"ACK {label} (seq {seq}) received -> stale/duplicate, ignored")

    def on_timeout(self, frame):
        self.say("Sender", f"Timeout occurred for frame {frame} -> frame or ACK lost, "
                           f"retransmitting the unacknowledged frame {frame}")
        self.retx_queue.append(frame)

    def receiver_on_frame(self, frame, seq):
        if seq == self.expected_seq:
            self.say("Receiver", f"Frame {frame} (seq {seq}) received successfully -> delivered")
            self.deliver(frame)
            self.expected_seq = (self.expected_seq + 1) % self.M
            self.rcv_next += 1
            self.send_ack(frame, seq)
        else:
            self.stats.discarded += 1
            self.say("Receiver", f"Frame {frame} (seq {seq}) is a duplicate (expected seq "
                                 f"{self.expected_seq}) -> discarded")
            self.send_ack(frame, seq, "re-ACK for duplicate, original ACK was probably lost")


# --------------------------------------------------------------------------- #
# Go-Back-N
# --------------------------------------------------------------------------- #
class GoBackN(ARQProtocol):
    NAME = "Go-Back-N"
    SHORT = "gbn"
    ASK_SENDER_WINDOW = True
    ASK_RECEIVER_WINDOW = False

    def __init__(self, cfg, log=print, observer=None):
        super().__init__(cfg, log, observer)
        self.expected_seq = 0                 # receiver window of size 1
        self.rcv_next = 0                     # absolute number of the next in-order frame

    @classmethod
    def check_windows(cls, cfg):
        errs = []
        space = 2 ** cfg.seq_bits
        if cfg.sender_window < 1 or cfg.sender_window > space - 1:
            errs.append(f"Go-Back-N sender window must be between 1 and 2^m - 1 = {space - 1} "
                        f"(got {cfg.sender_window} with m = {cfg.seq_bits}).")
        if cfg.receiver_window != 1:
            errs.append(f"Go-Back-N requires a receiver window of 1 (got {cfg.receiver_window}).")
        return errs

    def on_transmitted(self, frame, tx_end):
        # one timer, always for the oldest unacknowledged frame
        if frame == self.base:
            self.start_timer(frame, tx_end + self.cfg.timeout)

    def sender_on_ack(self, label, seq):
        outstanding = self.sent_hi - self.base
        offset = (seq - self.base) % self.M
        if offset < outstanding:
            top = self.base + offset
            self.say("Sender", f"ACK {label} received (cumulative) -> frames {self.base}..{top} acknowledged")
            self.stop_timer(self.base)
            for f in range(self.base, top + 1):
                self.acked[f] = True
            self.base = top + 1
            self.next_new = max(self.next_new, self.base)
            # restart the single timer for the new oldest frame (if it has already been sent)
            if self.base < self.sent_hi and self.next_new > self.base:
                self.start_timer(self.base, self.last_tx_end[self.base] + self.cfg.timeout)
        else:
            self.say("Sender", f"ACK {label} (seq {seq}) received -> duplicate, ignored")

    def on_timeout(self, frame):
        self.say("Sender", f"Timeout occurred for frame {frame} -> frame loss detected")
        self.say("Sender", f"Retransmitting outstanding frames {self.base}..{self.sent_hi - 1} (go back to {self.base})")
        self.retx_queue.clear()
        self.next_new = self.base             # go back: resend everything from the oldest unACKed frame

    def receiver_on_frame(self, frame, seq):
        if seq == self.expected_seq:
            self.say("Receiver", f"Frame {frame} (seq {seq}) received successfully -> delivered")
            self.deliver(frame)
            self.expected_seq = (self.expected_seq + 1) % self.M
            self.rcv_next += 1
            self.send_ack(frame, seq, f"cumulative: frames up to {frame} received")
        else:
            self.stats.discarded += 1
            kind = "duplicate" if frame < self.rcv_next else "out of order"
            self.say("Receiver", f"Frame {frame} (seq {seq}) is {kind} (expected seq "
                                 f"{self.expected_seq}) -> discarded")
            if self.rcv_next > 0:
                last = self.rcv_next - 1
                self.send_ack(last, last % self.M, f"re-ACK of last in-order frame {last}")
            else:
                self.say("Receiver", "No ACK sent (no frame has been received in order yet)")


# --------------------------------------------------------------------------- #
# Selective Repeat
# --------------------------------------------------------------------------- #
class SelectiveRepeat(ARQProtocol):
    NAME = "Selective Repeat"
    SHORT = "sr"
    ASK_SENDER_WINDOW = True
    ASK_RECEIVER_WINDOW = True

    def __init__(self, cfg, log=print, observer=None):
        super().__init__(cfg, log, observer)
        self.rcv_base = 0                     # receiver window base (absolute)
        self.rbuf = {}                        # buffered out-of-order frames: slot -> frame

    @classmethod
    def check_windows(cls, cfg):
        errs = []
        half = 2 ** cfg.seq_bits // 2
        if cfg.sender_window < 1 or cfg.sender_window > half:
            errs.append(f"Selective Repeat sender window must be between 1 and 2^(m-1) = {half} "
                        f"(got {cfg.sender_window} with m = {cfg.seq_bits}).")
        if cfg.receiver_window < 1 or cfg.receiver_window > half:
            errs.append(f"Selective Repeat receiver window must be between 1 and 2^(m-1) = {half} "
                        f"(got {cfg.receiver_window} with m = {cfg.seq_bits}).")
        return errs

    def on_transmitted(self, frame, tx_end):
        self.start_timer(frame, tx_end + self.cfg.timeout)   # an independent timer per frame

    def sender_on_ack(self, label, seq):
        outstanding = self.sent_hi - self.base
        offset = (seq - self.base) % self.M
        if offset >= outstanding:
            self.say("Sender", f"ACK {label} (seq {seq}) received -> outside the sender window, ignored")
            return
        frame = self.base + offset
        if self.acked[frame]:
            self.say("Sender", f"ACK {label} received -> frame {frame} already acknowledged, ignored")
            return
        self.acked[frame] = True
        self.stop_timer(frame)
        self.say("Sender", f"ACK {label} received -> frame {frame} acknowledged")
        if frame == self.base:
            old = self.base
            while self.base < self.N and self.acked[self.base]:
                self.base += 1
            self.next_new = max(self.next_new, self.base)
            self.say("Sender", f"Window slides: base {old} -> {self.base}")

    def on_timeout(self, frame):
        if self.acked[frame]:
            return
        self.say("Sender", f"Timeout occurred for frame {frame} -> frame loss detected")
        self.say("Sender", f"Retransmitting only frame {frame}")
        self.retx_queue.append(frame)

    def receiver_on_frame(self, frame, seq):
        offset = (seq - self.rcv_base) % self.M
        if offset < self.Wr:                                   # inside the receiver window
            slot = self.rcv_base + offset
            if slot in self.rbuf:
                self.stats.discarded += 1
                self.say("Receiver", f"Frame {frame} (seq {seq}) already buffered -> duplicate discarded")
                self.send_ack(frame, seq, "re-ACK")
                return
            self.rbuf[slot] = frame
            if offset == 0:
                self.say("Receiver", f"Frame {frame} (seq {seq}) received successfully (in order)")
            else:
                self.say("Receiver", f"Frame {frame} (seq {seq}) received out of order -> buffered "
                                     f"(receiver window {self.rcv_base}..{self.rcv_base + self.Wr - 1})")
            self.send_ack(frame, seq)
            first = self.rcv_base
            while self.rcv_base in self.rbuf:
                self.deliver(self.rbuf.pop(self.rcv_base))
                self.rcv_base += 1
            if self.rcv_base > first:
                span = f"{first}" if self.rcv_base - 1 == first else f"{first}..{self.rcv_base - 1}"
                self.say("Receiver", f"Delivered frame(s) {span} to the upper layer in order; "
                                     f"receiver window slides to base {self.rcv_base}")
        elif offset >= self.M - max(self.Wr, self.Ws):         # an already delivered frame
            # The receiver re-ACKs frames up to one *sender* window behind its base (not just one
            # receiver window), otherwise a lost ACK could never be recovered when Wr < Ws.
            self.stats.discarded += 1
            self.say("Receiver", f"Frame {frame} (seq {seq}) was already delivered -> duplicate discarded")
            self.send_ack(frame, seq, "re-ACK, the earlier ACK was probably lost")
        else:
            self.stats.discarded += 1
            self.say("Receiver", f"Frame {frame} (seq {seq}) is outside the receiver window -> discarded")


# --------------------------------------------------------------------------- #
# Protocol registry: the ONLY place that must change to add a new protocol
# --------------------------------------------------------------------------- #
PROTOCOLS = [StopAndWait, GoBackN, SelectiveRepeat]


def find_protocol(token):
    token = str(token).strip().lower()
    for i, cls in enumerate(PROTOCOLS, start=1):
        if token in (str(i), cls.SHORT, cls.NAME.lower()):
            return cls
    return None


# --------------------------------------------------------------------------- #
# Validation and running
# --------------------------------------------------------------------------- #
def validate_config(cfg, cls, enforce_windows=True):
    """Return (errors, warnings). With enforce_windows=False the window-size rules only warn."""
    errors, warnings = [], []
    if cfg.total_frames < 1:
        errors.append("Total number of frames must be at least 1.")
    if not 1 <= cfg.seq_bits <= 16:
        errors.append("Number of sequence bits must be between 1 and 16.")
    if errors:
        return errors, warnings
    for f in sorted(cfg.lost_frames):
        if not 0 <= f < cfg.total_frames:
            errors.append(f"Lost frame number {f} is outside the range 0..{cfg.total_frames - 1}.")
    for a in sorted(cfg.lost_acks):
        if not 0 <= a < cfg.total_frames:
            errors.append(f"Lost ACK number {a} is outside the range 0..{cfg.total_frames - 1}.")
    window_errors = cls.check_windows(cfg)
    if enforce_windows:
        errors += window_errors
    else:
        warnings += [f"(unsafe mode, not enforced) {w}" for w in window_errors]
    if cls is SelectiveRepeat and not window_errors and cfg.receiver_window < cfg.sender_window:
        warnings.append("Receiver window is smaller than the sender window: frames beyond the receiver "
                        "window will be discarded and retransmitted.")
    if cfg.timeout <= 2 * cfg.prop_delay:
        warnings.append("Timeout is not larger than the ACK round trip (2*Tp): expect spurious timeouts.")
    return errors, warnings


def run_simulation(cfg, cls, echo=True, observer=None):
    """Run one simulation. Returns (stats, list_of_log_lines). `observer` is optional (used by the GUI)."""
    lines = []

    def log(message):
        lines.append(message)
        if echo:
            print(message)

    sim = cls(cfg, log, observer)
    sim._log_len = lambda: len(lines)
    stats = sim.run()
    return stats, lines


# --------------------------------------------------------------------------- #
# Command-line / interactive front end
# --------------------------------------------------------------------------- #
def parse_number_list(text):
    text = text.strip().lower()
    if text in ("", "none", "-", "no", "n"):
        return set()
    out = set()
    for token in text.replace(";", ",").replace(" ", ",").split(","):
        if token.strip():
            out.add(int(token))
    return out


def ask_int(prompt, minimum=None):
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
        except ValueError:
            print("  Please enter a whole number.")
            continue
        if minimum is not None and value < minimum:
            print(f"  The value must be at least {minimum}.")
            continue
        return value


def ask_list(prompt):
    while True:
        try:
            return parse_number_list(input(prompt))
        except ValueError:
            print("  Please enter whole numbers separated by commas (or leave blank for none).")


def interactive_config():
    while True:
        print("========== GENERALIZED ARQ SIMULATOR ==========")
        print("Select ARQ Protocol:")
        for i, cls in enumerate(PROTOCOLS, start=1):
            print(f"{i}. {cls.NAME}")
        cls = None
        while cls is None:
            cls = find_protocol(input("Enter your choice: "))
            if cls is None:
                print(f"  Please enter a number between 1 and {len(PROTOCOLS)}.")
        frames = ask_int("Enter total number of frames: ", 1)
        bits = ask_int("Enter sequence number bits: ", 1)
        ws, wr = 1, 1
        if cls.ASK_SENDER_WINDOW:
            ws = ask_int("Enter sender window size: ", 1)
        if cls.ASK_RECEIVER_WINDOW:
            wr = ask_int("Enter receiver window size: ", 1)
        print("Configure channel errors:")
        lost_frames = ask_list("Enter frame numbers to be lost (comma separated, blank for none): ")
        lost_acks = ask_list("Enter ACK numbers to be lost (comma separated, blank for none): ")
        cfg = Config(frames, bits, ws, wr, lost_frames, lost_acks)
        errors, warnings = validate_config(cfg, cls)
        if errors:
            print("\nINVALID CONFIGURATION:")
            for e in errors:
                print(f"  - {e}")
            print("Please enter the configuration again.\n")
            continue
        for w in warnings:
            print(f"Warning: {w}")
        print()
        return cfg, cls


def build_parser():
    p = argparse.ArgumentParser(description="Generalized ARQ protocol simulator "
                                            "(run without --protocol for the interactive menu).")
    p.add_argument("--protocol", help="1/sw = Stop-and-Wait, 2/gbn = Go-Back-N, 3/sr = Selective Repeat")
    p.add_argument("--frames", type=int, help="total number of frames")
    p.add_argument("--bits", type=int, help="number of sequence number bits")
    p.add_argument("--sender-window", type=int, help="sender window size")
    p.add_argument("--receiver-window", type=int, help="receiver window size")
    p.add_argument("--lost-frames", default="", help="comma separated data frame numbers to lose, e.g. 3,7")
    p.add_argument("--lost-acks", default="", help="comma separated ACK numbers to lose, e.g. 5")
    p.add_argument("--frame-time", type=float, default=1.0, help="Tf, frame transmission time (default 1)")
    p.add_argument("--prop-delay", type=float, default=2.0, help="Tp, one-way propagation delay (default 2)")
    p.add_argument("--timeout", type=float, default=6.0, help="retransmission timeout (default 6)")
    p.add_argument("--unsafe", action="store_true",
                   help="demonstration only: do not enforce window-size limits (shows why they exist)")
    return p


def config_from_args(args):
    cls = find_protocol(args.protocol)
    if cls is None:
        raise SystemExit(f"Unknown protocol '{args.protocol}'. Use 1/sw, 2/gbn or 3/sr.")
    if args.frames is None or args.bits is None:
        raise SystemExit("--frames and --bits are required when --protocol is given.")
    ws = args.sender_window if args.sender_window is not None else (4 if cls.ASK_SENDER_WINDOW else 1)
    if args.receiver_window is not None:
        wr = args.receiver_window
    else:
        wr = ws if cls.ASK_RECEIVER_WINDOW else 1
    try:
        lost_frames = parse_number_list(args.lost_frames)
        lost_acks = parse_number_list(args.lost_acks)
    except ValueError:
        raise SystemExit("--lost-frames / --lost-acks must be comma separated whole numbers.")
    cfg = Config(args.frames, args.bits, ws, wr, lost_frames, lost_acks,
                 args.frame_time, args.prop_delay, args.timeout)
    return cfg, cls


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.protocol is None:
            cfg, cls = interactive_config()
            unsafe = False
        else:
            cfg, cls = config_from_args(args)
            unsafe = args.unsafe
            errors, warnings = validate_config(cfg, cls, enforce_windows=not unsafe)
            if errors:
                print("INVALID CONFIGURATION:")
                for e in errors:
                    print(f"  - {e}")
                return 2
            for w in warnings:
                print(f"Warning: {w}")
    except (EOFError, KeyboardInterrupt):
        print("\nInput ended - exiting.")
        return 1
    run_simulation(cfg, cls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
