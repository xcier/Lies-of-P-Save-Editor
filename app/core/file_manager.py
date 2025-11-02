from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

# ---------- simple logger ----------
def _log(*parts: Any) -> None:
    print("[file_manager]", *parts)

# ---------- uesave helpers ----------
def _uesave_path() -> str:
    # Prefer project-root uesave.exe; fall back to PATH
    here = Path(__file__).resolve().parents[2]
    exe = here / "uesave.exe"
    return str(exe if exe.exists() else "uesave")

def ensure_uesave_ok() -> Tuple[str, str]:
    exe = _uesave_path()
    proc = subprocess.run([exe, "--version"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"uesave not found/working: rc={proc.returncode} stderr={proc.stderr.strip()}")
    _log("uesave ok:", exe, proc.stdout.strip())
    return exe, proc.stdout.strip()

# ---------- JSON utils ----------
def _dumps_pretty(obj: Any) -> bytes:
    # pretty, multi-line for human editing; ensure ASCII off for game strings
    txt = json.dumps(obj, ensure_ascii=False, indent=2)
    return txt.encode("utf-8")

def _dumps_compact(obj: Any) -> bytes:
    # used for piping to uesave (smaller)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return txt.encode("utf-8")

# ---------- shape-preserving merge ----------
def _merge_preserving_schema(base: Any, edited: Any, path: str = "$") -> Any:
    """
    Merge `edited` into `base` without changing the schema shape uesave expects.
    Rules:
      - If base is a {"tag":X,"value":Y} dict, recurse into value only.
      - If both are dicts (and not tagged), merge by keys; unknown keys ignored.
      - If both are lists, merge by index; on length mismatch, keep base.
      - If both are primitives and types match, take edited; else keep base.
    """
    # Tagged node: only value is editable, tag must be preserved.
    if isinstance(base, dict) and "tag" in base and "value" in base and isinstance(base["tag"], str):
        new_val = base["value"]
        if edited is not None:
            # If edited looks like a bare payload (not tagged), merge into value.
            new_val = _merge_preserving_schema(base["value"], edited, path + ".value")
        return {"tag": base["tag"], "value": new_val}

    # Plain dicts
    if isinstance(base, dict) and isinstance(edited, dict):
        out = dict(base)  # start from base
        for k, v in edited.items():
            if k not in base:
                # Don’t invent new keys in schema-critical nodes
                continue
            out[k] = _merge_preserving_schema(base[k], v, f"{path}.{k}")
        return out

    # Lists
    if isinstance(base, list) and isinstance(edited, list):
        # Keep list length from base; merge index-by-index
        out = list(base)
        rng = min(len(base), len(edited))
        for i in range(rng):
            out[i] = _merge_preserving_schema(base[i], edited[i], f"{path}[{i}]")
        return out

    # Primitives
    if (isinstance(base, (str, int, float, bool)) or base is None) and (
        isinstance(edited, (str, int, float, bool)) or edited is None
    ):
        # Only take edited if type matches base (or base is None)
        if (base is None) or (type(base) is type(edited)):
            return edited
        return base

    # Fallback: keep base (avoids “expected sequence/map” errors)
    return base

# ---------- run uesave ----------
def _run(exe: str, args: list[str], *, stdin: Optional[bytes] = None, timeout: Optional[int] = None) -> Tuple[int, bytes, bytes]:
    proc = subprocess.Popen([exe] + args, stdin=subprocess.PIPE if stdin is not None else None,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate(input=stdin, timeout=timeout)
    return proc.returncode, out, err

# ---------- public API ----------
class FileManager:
    @staticmethod
    def load_file(path: str) -> dict:
        """
        Loads .sav or .json
        - For .sav: run uesave to-json and parse, returning dict the UI uses.
        - For .json: read and parse directly.
        """
        ensure_uesave_ok()
        p = Path(path)
        if p.suffix.lower() == ".json":
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data

        # .sav -> JSON dict
        exe, _ = ensure_uesave_ok()
        rc, out, err = _run(exe, ["to-json", "--input", str(p)], timeout=120)
        if rc != 0:
            raise RuntimeError(f"to-json failed: {err.decode('utf-8','ignore').strip()}")
        data = json.loads(out.decode("utf-8"))
        return data

    @staticmethod
    def save_sav(target_path: str,
                 edited_data: dict,
                 src_path: str,
                 on_progress: Optional[Callable[[int, str], None]] = None) -> str:
        """
        Build schema-correct JSON by merging edits into a fresh baseline from uesave to-json,
        then stream it to uesave from-json.
        """
        def ping(p: int, m: str): 
            try:
                on_progress and on_progress(p, m)
            except Exception:
                pass

        exe, _ = ensure_uesave_ok()
        target_path = str(Path(target_path).resolve())
        src_path = str(Path(src_path).resolve()) if src_path else target_path

        # 1) Get fresh baseline from current (or original) .sav
        ping(45, "Reading baseline via to-json")
        rc, base_json_bytes, err = _run(exe, ["to-json", "--input", src_path], timeout=120)
        if rc != 0:
            raise RuntimeError(f"to-json failed: {err.decode('utf-8','ignore').strip()}")

        try:
            baseline = json.loads(base_json_bytes.decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"baseline JSON parse failed: {e}")

        # 2) Merge – preserve all tags/types/containers
        ping(55, "Merging changes")
        merged = _merge_preserving_schema(baseline, edited_data, "$")

        # 3) Save a pretty copy for inspection
        dbg_dir = Path(target_path).with_suffix("").parent
        dbg_dir.mkdir(parents=True, exist_ok=True)
        pretty_copy = Path(target_path).with_suffix(".merged.json")
        try:
            pretty_copy.write_bytes(_dumps_pretty(merged))
        except Exception:
            pass  # not fatal

        # 4) Stream to uesave from-json (no shell redirection; works in PowerShell/CMD)
        ping(60, "Invoking uesave (from-json)")
        merged_bytes = _dumps_compact(merged)
        tmp_out = str(Path(target_path).with_suffix(".sav.part"))

        rc, out, err = _run(exe, ["from-json"], stdin=merged_bytes, timeout=180)
        if rc != 0:
            # Write failing payload for inspection
            failed_copy = Path(target_path).with_suffix(".failed.json")
            try:
                failed_copy.write_bytes(_dumps_pretty(merged))
            except Exception:
                pass
            raise RuntimeError(err.decode("utf-8", "ignore").strip() or "from-json failed")

        # 5) Write binary .sav
        with open(tmp_out, "wb") as f:
            f.write(out)

        final = Path(target_path)
        # atomic-ish move
        if final.exists():
            final.unlink(missing_ok=True)
        shutil.move(tmp_out, final)
        ping(100, "Saved")
        return str(final)