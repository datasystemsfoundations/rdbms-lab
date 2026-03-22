# B-Trees: Forensic Exploration with SQLite

Hands-on lab for understanding B+Tree internals — how inserts cause splits, the O(log N) write overhead, index tax, and how joins leverage B-tree indexes.

## Files

| File | Purpose |
|------|---------|
| `setup.sh` | Installs all dependencies (one-time) |
| `lab_btrees.ipynb` | The lab notebook — run this |
| `btree_viz.py` | B+Tree implementation + graphviz visualizer (used by the notebook) |
| `.gitignore` | Keeps generated files out of the repo |

All generated artifacts (images, `.db` files, `.dot` files) are written to `_output/` at runtime.

## Setup

```bash
# 1. Install dependencies
bash setup.sh

# 2. Activate the virtual environment
source .venv/bin/activate

# 3. Open the lab
jupyter notebook lab_btrees.ipynb
```

## Prerequisites

- Python 3.10+
- macOS (Homebrew) or Linux (apt)
- SQLite (comes with Python)
