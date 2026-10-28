# Comparison tables

Time units: frame transmission = 1, one-way propagation = 2, timeout = 6 (ACK round trip = 4). Each lost frame/ACK is lost on its first transmission only. Ws / Wr are the sender / receiver window sizes. "Discarded" counts frames that reached the receiver but were not accepted (out of order in GBN, duplicates in all protocols).

## Headline scenario (the assignment's sample input)

10 frames, m = 3, window 4, frames 3 and 7 lost, ACK 5 lost - all three protocol selections.

| Protocol | Ws / Wr | Delivered | Transmission attempts | Retransmissions | Discarded | Timeouts | Simulated time |
|---|---|---|---|---|---|---|---|
| Stop-and-Wait | 1 / 1 | 10/10 | 13 | 3 | 1 | 3 | 71 |
| Go-Back-N | 4 / 1 | 10/10 | 17 | 7 | 5 | 2 | 29 |
| Selective Repeat | 4 / 4 | 10/10 | 13 | 3 | 1 | 3 | 27 |

## Test 1 - No frame or ACK loss

Baseline: shows the throughput benefit of pipelining (window 4 for GBN and SR).

| Protocol | Ws / Wr | Delivered | Transmission attempts | Retransmissions | Discarded | Timeouts | Simulated time |
|---|---|---|---|---|---|---|---|
| Stop-and-Wait | 1 / 1 | 10/10 | 10 | 0 | 0 | 0 | 50 |
| Go-Back-N | 4 / 1 | 10/10 | 10 | 0 | 0 | 0 | 16 |
| Selective Repeat | 4 / 4 | 10/10 | 10 | 0 | 0 | 0 | 16 |

## Test 2 - One data frame lost

Frame 3 is lost on its first transmission.

| Protocol | Ws / Wr | Delivered | Transmission attempts | Retransmissions | Discarded | Timeouts | Simulated time |
|---|---|---|---|---|---|---|---|
| Stop-and-Wait | 1 / 1 | 10/10 | 11 | 1 | 0 | 1 | 57 |
| Go-Back-N | 4 / 1 | 10/10 | 14 | 4 | 3 | 1 | 22 |
| Selective Repeat | 4 / 4 | 10/10 | 11 | 1 | 0 | 1 | 22 |

## Test 3a - One ACK lost

ACK 5 is lost. GBN's cumulative ACK 6 makes up for it; SR and Stop-and-Wait must time out.

| Protocol | Ws / Wr | Delivered | Transmission attempts | Retransmissions | Discarded | Timeouts | Simulated time |
|---|---|---|---|---|---|---|---|
| Stop-and-Wait | 1 / 1 | 10/10 | 11 | 1 | 1 | 1 | 57 |
| Go-Back-N | 4 / 1 | 10/10 | 10 | 0 | 0 | 0 | 17 |
| Selective Repeat | 4 / 4 | 10/10 | 11 | 1 | 1 | 1 | 23 |

## Test 3b - The last ACK lost

ACK 9 is lost and no later ACK can cover it, so every protocol must time out and retransmit.

| Protocol | Ws / Wr | Delivered | Transmission attempts | Retransmissions | Discarded | Timeouts | Simulated time |
|---|---|---|---|---|---|---|---|
| Stop-and-Wait | 1 / 1 | 10/10 | 11 | 1 | 1 | 1 | 57 |
| Go-Back-N | 4 / 1 | 10/10 | 11 | 1 | 1 | 1 | 23 |
| Selective Repeat | 4 / 4 | 10/10 | 11 | 1 | 1 | 1 | 23 |

## Test 4 - Multiple consecutive data frames lost

Frames 3, 4 and 5 are lost one after another.

| Protocol | Ws / Wr | Delivered | Transmission attempts | Retransmissions | Discarded | Timeouts | Simulated time |
|---|---|---|---|---|---|---|---|
| Stop-and-Wait | 1 / 1 | 10/10 | 13 | 3 | 0 | 3 | 71 |
| Go-Back-N | 4 / 1 | 10/10 | 14 | 4 | 1 | 1 | 22 |
| Selective Repeat | 4 / 4 | 10/10 | 13 | 3 | 0 | 3 | 23 |

## Test 5 - Different sender window sizes for GBN and SR

Frames 3 and 7 lost, m = 3. GBN windows 1, 2, 4, 7 (max 2^m - 1 = 7); SR windows 1, 2, 4 (max 2^(m-1) = 4); Stop-and-Wait shown for reference. The last row uses a receiver window smaller than the sender window.

| Protocol | Ws / Wr | Delivered | Transmission attempts | Retransmissions | Discarded | Timeouts | Simulated time |
|---|---|---|---|---|---|---|---|
| Stop-and-Wait | 1 / 1 | 10/10 | 12 | 2 | 0 | 2 | 64 |
| Go-Back-N | 1 / 1 | 10/10 | 12 | 2 | 0 | 2 | 64 |
| Go-Back-N | 2 / 1 | 10/10 | 14 | 4 | 2 | 2 | 40 |
| Go-Back-N | 4 / 1 | 10/10 | 17 | 7 | 5 | 2 | 29 |
| Go-Back-N | 7 / 1 | 10/10 | 17 | 7 | 5 | 1 | 21 |
| Selective Repeat | 1 / 1 | 10/10 | 12 | 2 | 0 | 2 | 64 |
| Selective Repeat | 2 / 2 | 10/10 | 12 | 2 | 0 | 2 | 40 |
| Selective Repeat | 4 / 4 | 10/10 | 12 | 2 | 0 | 2 | 27 |
| Selective Repeat | 4 / 2 | 10/10 | 15 | 5 | 3 | 5 | 30 |

- Selective Repeat (Ws=4, Wr=2, m=3): Wr < Ws: frames beyond the receiver window are discarded and resent

## Test 6 - Different sequence number bit lengths

Frames 3 and 7 lost. For m = 1..4 each protocol uses the largest window its sequence space allows: the number of bits caps the window, and therefore the throughput.

| Protocol | Ws / Wr | Delivered | Transmission attempts | Retransmissions | Discarded | Timeouts | Simulated time |
|---|---|---|---|---|---|---|---|
| Go-Back-N | 1 / 1 (m=1) | 10/10 | 12 | 2 | 0 | 2 | 64 |
| Selective Repeat | 1 / 1 (m=1) | 10/10 | 12 | 2 | 0 | 2 | 64 |
| Go-Back-N | 3 / 1 (m=2) | 10/10 | 16 | 6 | 4 | 2 | 32 |
| Selective Repeat | 2 / 2 (m=2) | 10/10 | 12 | 2 | 0 | 2 | 40 |
| Go-Back-N | 7 / 1 (m=3) | 10/10 | 17 | 7 | 5 | 1 | 21 |
| Selective Repeat | 4 / 4 (m=3) | 10/10 | 12 | 2 | 0 | 2 | 27 |
| Go-Back-N | 15 / 1 (m=4) | 10/10 | 17 | 7 | 5 | 1 | 21 |
| Selective Repeat | 8 / 8 (m=4) | 10/10 | 12 | 2 | 0 | 2 | 19 |

## Test 7 - Invalid configurations

The simulator must reject each of these before any transmission starts.

| Protocol | Configuration tried | Result |
|---|---|---|
| Selective Repeat | SR window 5 > 2^(m-1) = 4 | REJECTED: Selective Repeat sender window must be between 1 and 2^(m-1) = 4 (got 5 with m = 3). Selective Repeat receiver window must be between 1 and 2^(m-1) = 4 (got 5 with m = 3). |
| Selective Repeat | SR receiver window 5 > 2^(m-1) = 4 | REJECTED: Selective Repeat receiver window must be between 1 and 2^(m-1) = 4 (got 5 with m = 3). |
| Go-Back-N | GBN window 8 > 2^m - 1 = 7 | REJECTED: Go-Back-N sender window must be between 1 and 2^m - 1 = 7 (got 8 with m = 3). |
| Go-Back-N | GBN receiver window must be 1 | REJECTED: Go-Back-N requires a receiver window of 1 (got 2). |
| Stop-and-Wait | Stop-and-Wait window must be 1 | REJECTED: Stop-and-Wait requires a sender window of 1 (got 2). |
| Selective Repeat | zero frames | REJECTED: Total number of frames must be at least 1. |
| Go-Back-N | zero sequence bits | REJECTED: Number of sequence bits must be between 1 and 16. |
| Go-Back-N | lost frame / ACK numbers out of range | REJECTED: Lost frame number 12 is outside the range 0..9. Lost ACK number 15 is outside the range 0..9. |

## Test 7b - Why the window must be limited (demonstration)

With m = 2 and ACKs 0-2 lost, an oversized SR window makes the receiver accept an old retransmission as a brand-new frame (sequence-number ambiguity). The legal window does not.

| Protocol | Ws / Wr | Delivered | Transmission attempts | Retransmissions | Discarded | Timeouts | Simulated time |
|---|---|---|---|---|---|---|---|
| Selective Repeat | 3 / 3 | 6/6 (FAILED) | 9 | 3 | 2 | 3 | 19 |
| Selective Repeat | 2 / 2 | 6/6 | 9 | 3 | 3 | 3 | 30 |

- Selective Repeat (Ws=3, Wr=3, m=2): UNSAFE: m=2, SR window 3 > 2^(m-1) = 2, window check bypassed with --unsafe
- Selective Repeat (Ws=2, Wr=2, m=2): same channel errors with the legal window 2 = 2^(m-1)

