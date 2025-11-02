from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Iterable, Optional, List

__all__ = ["find_app_icon"]

def _iter_candidate_roots() -> List[Path]:
    """
    Candidate roots to search for resources, ordered by usefulness.
    Covers dev runs and frozen/packaged (PyInstaller) runs.
    """
    roots: List[Path] = []

    # Packaged (PyInstaller) locations
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)  # type: ignore[attr-defined]
        if meipass:
            try:
                roots.append(Path(meipass))
            except Exception:
                pass
        try:
            roots.append(Path(sys.executable).parent)  # folder with the exe/bundle
        except Exception:
            pass

    # Source tree: .../app/utils/resources.py -> go up to /app
    try:
        roots.append(Path(__file__).resolve().parents[1])
    except Exception:
        pass

    # Script dir (main module) and current working directory
    try:
        main_dir = Path(sys.modules["__main__"].__file__).resolve().parent  # type: ignore[attr-defined]
        roots.append(main_dir)
    except Exception:
        pass

    try:
        roots.append(Path.cwd())
    except Exception:
        pass

    # De-duplicate while preserving order
    seen = set()
    uniq: List[Path] = []
    for r in roots:
        if r and r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq

def find_app_icon() -> Optional[str]:
    """
    Return a filesystem path to the app icon (ICO/PNG), or None if not found.

    Priority:
      1) APP_ICON_HINT env var (absolute or relative to CWD) if it exists
      2) Platform-preferred extensions:
         - Windows: .ico first, then .png
         - macOS/Linux: .png first, then .ico
      3) Search locations (in each candidate root):
         - app/resources/
         - resources/
         - (root itself)
    """
    # 1) Env override
    hint = os.environ.get("APP_ICON_HINT")
    if hint:
        p = Path(hint)
        if not p.is_absolute():
            p = Path.cwd() / p
        try:
            if p.exists():
                return str(p)
        except Exception:
            # Ignore bad path errors and continue to normal search
            pass

    # 2) Extension preference by platform
    if os.name == "nt":
        exts = (".ico", ".png")
    else:
        exts = (".png", ".ico")

    names = [f"app{ext}" for ext in exts] + [f"icon{ext}" for ext in exts]
    subdirs = ("app/resources", "resources", "")  # .\app\resources\app.ico preferred first

    # 3) Search
    for root in _iter_candidate_roots():
        for sub in subdirs:
            base = (root / sub) if sub else root
            for name in names:
                candidate = base / name
                try:
                    if candidate.exists():
                        return str(candidate)
                except Exception:
                    # Permission issues or odd FS errors — skip and continue
                    continue

    return None