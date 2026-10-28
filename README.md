# ARQ Studio

An interactive simulator for **Automatic Repeat reQuest (ARQ)** protocols, designed to demonstrate how reliable data transmission works over an unreliable communication channel.

ARQ Studio simulates frame transmission, acknowledgements, frame loss, ACK loss, retransmissions, and protocol performance to help students understand Data Link Layer flow control and error recovery.

## Features

- **Three ARQ protocols**
  - Stop-and-Wait ARQ
  - Go-Back-N ARQ
  - Selective Repeat ARQ
- Configurable number of frames and sequence number bits
- Configurable sender and receiver window sizes, where applicable
- Simulation of frame and acknowledgement loss
- Protocol-specific retransmission and error recovery
- Performance statistics, including transmission attempts, retransmissions, delivered frames, discarded frames, and simulated time
- Test scenarios for comparing protocol behavior

## Protocols Explained

| Protocol | Receiver Window | Recovery Mechanism |
|---|---:|---|
| Stop-and-Wait | 1 | Retransmits the unacknowledged frame |
| Go-Back-N | 1 | Retransmits outstanding frames starting from the oldest unacknowledged frame |
| Selective Repeat | Configurable | Retransmits only the unacknowledged frames that require recovery |

## Tech Stack

- Python
- Git and GitHub

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/OmHimthani/ARQ_Studio.git
cd ARQ_Studio
```

### 2. Run the simulator

If the current version uses the command-line interface:

```bash
python arq_simulator.py
```

### 3. Run the tests

```bash
python run_tests.py
```

> Adjust the filenames or commands if your current project uses a different entry point.

## How It Works

1. Select an ARQ protocol.
2. Configure the transmission parameters.
3. Specify frame-loss and acknowledgement-loss scenarios.
4. Run the simulation.
5. Observe frame delivery, acknowledgements, retransmissions, and recovery behavior.
6. Compare performance across the supported protocols.

## Learning Objectives

- Understand reliable data transmission at the Data Link Layer.
- Learn the difference between individual and cumulative acknowledgements.
- Understand sequence number spaces and sliding windows.
- Analyze the effect of frame loss and ACK loss.
- Compare retransmission strategies across ARQ protocols.

## Project Structure

```text
ARQ_Studio/
├── README.md
├── arq_simulator.py
├── run_tests.py
├── execution_logs.txt
└── comparison_table.md
```

The structure above is illustrative; update it to match the files actually present in the repository.

## Academic Context

Developed as part of a Data Communication laboratory assignment on Data Link Layer flow-control protocols.

## Author

**Om Himthani**

GitHub: [@OmHimthani](https://github.com/OmHimthani)

---

If you find this project useful for learning ARQ protocols, feel free to explore the code and experiment with different simulation scenarios.
