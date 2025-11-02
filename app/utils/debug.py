from __future__ import annotations
import os, datetime

# Log file goes to system temp dir
LOGFILE = os.path.join(os.getenv("TEMP") or os.getcwd(), "lop_debug.log")

def log(msg: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        # last-ditch: print to stdout
        print(f"[{ts}] {msg}")
