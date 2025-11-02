from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

# ---------- simple logger ----------
def _log(*parts: Any) -> None:
    print("[file_manager]", *parts)


# ---------- uesave helpers ----------

def _uesave_candidates() -> list[Path]:
    """
    All the places we’re willing to look for uesave.exe.

    Supports:
    - dev run (python main.py)
    - PyInstaller onedir build
    - PyInstaller onefile build (extracted to _MEIPASS temp dir)
    """
    cands: list[Path] = []

    # 1. Frozen / packaged build
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        # next to LiesOfPSaveEditor.exe (onedir, or user copies it manually)
        cands.append(exe_dir / "uesave.exe")
        cands.append(exe_dir / "uesave")
        # in app/resources next to the exe (our onedir layout)
        cands.append(exe_dir / "app" / "resources" / "uesave.exe")
        cands.append(exe_dir / "app" / "resources" / "uesave")

        # onefile runtime extraction dir
        # PyInstaller extracts bundled stuff to sys._MEIPASS
        bundle_dir = Path(getattr(sys, "_MEIPASS", exe_dir))
        cands.append(bundle_dir / "uesave.exe")
        cands.append(bundle_dir / "uesave")
        cands.append(bundle_dir / "app" / "resources" / "uesave.exe")
        cands.append(bundle_dir / "app" / "resources" / "uesave")

    # 2. Dev run (source tree)
    # file_manager.py = app/core/file_manager.py
    repo_root = Path(__file__).resolve().parents[2]
    cands.append(repo_root / "uesave.exe")
    cands.append(repo_root / "uesave")
    cands.append(repo_root / "app" / "resources" / "uesave.exe")
    cands.append(repo_root / "app" / "resources" / "uesave")

    # de-dupe while preserving order
    seen = set()
    uniq: list[Path] = []
    for p in cands:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _uesave_path() -> str:
    """
    Pick the first existing candidate for uesave.
    Fallback to bare 'uesave' so PATH can still satisfy us.
    """
    for cand in _uesave_candidates():
        if cand.exists():
            return str(cand)
    return "uesave"


def ensure_uesave_ok() -> Tuple[str, str]:
    """
    Make sure we can actually run uesave.
    Returns (exe_path, version_text) or raises RuntimeError.
    """
    exe = _uesave_path()
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        # WinError 2 / not found
        raise RuntimeError(f"uesave not found/working: {e}")

    if proc.returncode != 0:
        raise RuntimeError(
            f"uesave not found/working: rc={proc.returncode} stderr={proc.stderr.strip()}"
        )

    version_txt = proc.stdout.strip()
    _log("uesave ok:", exe, version_txt)
    return exe, version_txt


# ---------- JSON utils ----------

def _dumps_pretty(obj: Any) -> bytes:
    """
    Pretty multi-line JSON for humans. Non-ASCII preserved.
    """
    txt = json.dumps(obj, ensure_ascii=False, indent=2)
    return txt.encode("utf-8")


def _dumps_compact(obj: Any) -> bytes:
    """
    Compact JSON fed into uesave via stdin (smaller, faster).
    """
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return txt.encode("utf-8")


# ---------- shape-preserving merge ----------

def _merge_preserving_schema(base: Any, edited: Any, path: str = "$") -> Any:
    """
    Merge `edited` into `base` while preserving the Unreal/uesave schema.

    Rules:
      - If base is {"tag": <str>, "value": <payload>}, we ONLY merge into .value,
        and we must keep .tag from base.
      - Dicts: merge known keys only (don't invent new keys, keeps struct layout stable).
      - Lists: merge index-by-index up to min length; don't resize arrays.
      - Primitives: take edited if type matches base (or base is None).
      - Otherwise: keep base.
    """

    # Tagged node: {"tag": "...", "value": ...}
    if (
        isinstance(base, dict)
        and "tag" in base
        and "value" in base
        and isinstance(base["tag"], str)
    ):
        new_val = base["value"]
        if edited is not None:
            # Merging user edits into the value branch only.
            new_val = _merge_preserving_schema(base["value"], edited, path + ".value")
        return {"tag": base["tag"], "value": new_val}

    # Plain dicts
    if isinstance(base, dict) and isinstance(edited, dict):
        out = dict(base)
        for k, v in edited.items():
            if k not in base:
                # do not create brand-new keys that weren't already there
                continue
            out[k] = _merge_preserving_schema(base[k], v, f"{path}.{k}")
        return out

    # Lists
    if isinstance(base, list) and isinstance(edited, list):
        out = list(base)
        limit = min(len(base), len(edited))
        for i in range(limit):
            out[i] = _merge_preserving_schema(base[i], edited[i], f"{path}[{i}]")
        return out

    # Primitives
    if (
        (isinstance(base, (str, int, float, bool)) or base is None)
        and (isinstance(edited, (str, int, float, bool)) or edited is None)
    ):
        if (base is None) or (type(base) is type(edited)):
            return edited
        return base

    # Fallback: don't mutate structure
    return base


# ---------- run uesave low-level ----------

def _run(
    exe: str,
    args: list[str],
    *,
    stdin: Optional[bytes] = None,
    timeout: Optional[int] = None,
):
    """
    Run uesave with given args.
    We capture stdout/stderr directly instead of relying on shell redirection.
    """
    proc = subprocess.Popen(
        [exe] + args,
        stdin=subprocess.PIPE if stdin is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = proc.communicate(input=stdin, timeout=timeout)
    return proc.returncode, out, err


# ---------- public API ----------

class FileManager:
    @staticmethod
    def load_file(path: str) -> dict:
        """
        Load either:
        - .json (already exported/edited JSON)
        - .sav  (binary Lies of P save, will be run through uesave to-json)
        Returns a Python dict suitable for the rest of the UI.
        """
        ensure_uesave_ok()

        p = Path(path)
        if p.suffix.lower() == ".json":
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)

        exe, _ = ensure_uesave_ok()
        rc, out, err = _run(exe, ["to-json", "--input", str(p)], timeout=120)
        if rc != 0:
            raise RuntimeError(
                f"to-json failed: {err.decode('utf-8','ignore').strip()}"
            )

        data = json.loads(out.decode("utf-8"))
        return data

    @staticmethod
    def save_sav(
        target_path: str,
        edited_data: dict,
        src_path: str,
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        """
        Save a new .sav using current edits.

        Steps:
          1. Pull a baseline from a known-good .sav using uesave to-json.
          2. Merge the user's edits into that baseline WITHOUT changing structure.
          3. Write a human-readable .merged.json next to the output (debug).
          4. Pipe the merged compact JSON to uesave from-json.
          5. Write the resulting binary .sav.

        on_progress(pct:int, msg:str) is optional UI callback.
        """
        def ping(pct: int, msg: str) -> None:
            try:
                if on_progress:
                    on_progress(pct, msg)
            except Exception:
                # UI callback shouldn't crash the save
                pass

        exe, _ = ensure_uesave_ok()

        # normalize paths
        target_path = str(Path(target_path).resolve())
        src_path = str(Path(src_path).resolve()) if src_path else target_path

        # 1) baseline JSON from src .sav
        ping(45, "Reading baseline via to-json")
        rc, base_json_bytes, err = _run(
            exe,
            ["to-json", "--input", src_path],
            timeout=120,
        )
        if rc != 0:
            raise RuntimeError(
                f"to-json failed: {err.decode('utf-8','ignore').strip()}"
            )

        try:
            baseline = json.loads(base_json_bytes.decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"baseline JSON parse failed: {e}")

        # 2) merge edits over baseline without breaking UE layout
        ping(55, "Merging changes")
        merged = _merge_preserving_schema(baseline, edited_data, "$")

        # 3) write pretty debug copy
        dbg_dir = Path(target_path).with_suffix("").parent
        dbg_dir.mkdir(parents=True, exist_ok=True)

        pretty_copy = Path(target_path).with_suffix(".merged.json")
        try:
            pretty_copy.write_bytes(_dumps_pretty(merged))
        except Exception:
            pass  # non-fatal

        # 4) rebuild binary via uesave from-json
        ping(60, "Invoking uesave (from-json)")
        merged_bytes = _dumps_compact(merged)

        tmp_out = str(Path(target_path).with_suffix(".sav.part"))

        rc, out, err = _run(
            exe,
            ["from-json"],
            stdin=merged_bytes,
            timeout=180,
        )
        if rc != 0:
            # write failing payload for debugging
            failed_copy = Path(target_path).with_suffix(".failed.json")
            try:
                failed_copy.write_bytes(_dumps_pretty(merged))
            except Exception:
                pass

            raise RuntimeError(
                err.decode("utf-8", "ignore").strip() or "from-json failed"
            )

        # 5) atomically move final bytes into place
        with open(tmp_out, "wb") as f:
            f.write(out)

        final = Path(target_path)
        if final.exists():
            final.unlink(missing_ok=True)
        shutil.move(tmp_out, final)

        ping(100, "Saved")
        return str(final)
