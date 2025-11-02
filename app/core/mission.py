from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional, Union, Set
import copy, string

JSON = Union[dict, list, str, int, float, bool, None]

# Public for UI / dropdowns
QUEST_STATES = ["Inactive", "In Progress", "Complete Success", "Complete Fail"]

# ---------------- tiny utils ----------------
def _lkeys(d: Dict[str, Any]) -> Dict[str, str]:
    """lower -> original key map"""
    return {str(k).lower(): k for k in d}

def _norm_enum(s: str) -> str:
    s = (s or "").strip()
    return s.replace("::", "_").replace("-", "_").replace(" ", "_").upper()

def _retarget_enum_like(current_raw: Any, canonical_raw: Any) -> str:
    """Keep the save's prefix (e.g., ELQUESTSTATE_) while applying canonical E_* value."""
    cur = _norm_enum("" if current_raw is None else str(current_raw))
    canon = _norm_enum("" if canonical_raw is None else str(canonical_raw))
    i = cur.find("E_")
    if i != -1:
        prefix = cur[:i]
        if prefix and not prefix.endswith("_"):
            prefix += "_"
        return prefix + canon
    return canon

def _get(obj: JSON, path: List[Union[str, int]]) -> JSON:
    cur = obj
    for p in path:
        if isinstance(cur, dict) and isinstance(p, str):
            lk = _lkeys(cur); key = lk.get(p.lower())
            cur = cur.get(key) if key is not None else None
        elif isinstance(cur, list) and isinstance(p, int):
            if 0 <= p < len(cur):
                cur = cur[p]
            else:
                return None
        else:
            return None
    return cur

def _set(obj: JSON, path: List[Union[str,int]], val: Any) -> bool:
    if not path: return False
    cur = obj
    for p in path[:-1]:
        if isinstance(cur, dict) and isinstance(p, str):
            lk = _lkeys(cur); key = lk.get(p.lower())
            cur = cur.get(key) if key is not None else None
        elif isinstance(cur, list) and isinstance(p, int):
            if 0 <= p < len(cur): cur = cur[p]
            else: return False
        else:
            return False
        if cur is None: return False
    last = path[-1]
    if isinstance(cur, dict) and isinstance(last, str):
        lk = _lkeys(cur); key = lk.get(last.lower(), last)
        cur[key] = val; return True
    if isinstance(cur, list) and isinstance(last, int) and 0 <= last < len(cur):
        cur[last] = val; return True
    return False

def _clone(obj: JSON) -> JSON:
    return copy.deepcopy(obj)

def _is_scalar(x: Any) -> bool:
    return isinstance(x, (str, int, float, bool)) or x is None

# ---------------- unwrapping (case-insensitive) ----------------
_WRAPPER_KEYS = {"struct", "data", "value", "tag"}

def _unwrap(node: JSON, max_depth: int = 12) -> JSON:
    cur = node; depth = 0
    while depth < max_depth and isinstance(cur, dict):
        lk = _lkeys(cur)
        # Array node (case-insensitive)
        arrk = lk.get("array")
        if arrk and isinstance(cur[arrk], dict):
            a = cur[arrk]
            alk = _lkeys(a)
            # Array.Struct.value
            if alk.get("struct") and isinstance(a[alk["struct"]], dict):
                sv = a[alk["struct"]]; svlk = _lkeys(sv)
                if svlk.get("value") and isinstance(sv[svlk["value"]], list):
                    return sv[svlk["value"]]
            # Array.value
            if alk.get("value") and isinstance(a[alk["value"]], list):
                return a[alk["value"]]
            cur = a; depth += 1; continue

        # Generic wrapper keys (case-insensitive)
        advanced = False
        for want in _WRAPPER_KEYS:
            wk = lk.get(want)
            if wk and isinstance(cur[wk], (dict, list)):
                cur = cur[wk]; depth += 1; advanced = True; break
        if advanced: continue

        # Explicit Struct (case-insensitive)
        sk = lk.get("struct")
        if sk and isinstance(cur[sk], (dict, list)):
            cur = cur[sk]; depth += 1; continue

        break
    return cur

def _unwrap_with_path(node: JSON, base: List[Union[str,int]], max_depth: int = 12) -> Tuple[JSON, List[Union[str,int]]]:
    """Return (unwrapped_node, absolute_path_to_that_unwrapped_node). Case-insensitive pathing."""
    cur = node; path = list(base); depth = 0
    while depth < max_depth and isinstance(cur, dict):
        lk = _lkeys(cur)
        # Array
        arrk = lk.get("array")
        if arrk and isinstance(cur[arrk], dict):
            path.append(arrk)
            a = cur[arrk]; alk = _lkeys(a)
            if alk.get("struct") and isinstance(a[alk["struct"]], dict):
                sv = a[alk["struct"]]; svlk = _lkeys(sv)
                if svlk.get("value") and isinstance(sv[svlk["value"]], list):
                    path.extend([alk["struct"], svlk["value"]]); return sv[svlk["value"]], path
            if alk.get("value") and isinstance(a[alk["value"]], list):
                path.append(alk["value"]); return a[alk["value"]], path
            cur = a; depth += 1; continue

        # Generic wrappers
        advanced = False
        for want in _WRAPPER_KEYS:
            wk = lk.get(want)
            if wk and isinstance(cur[wk], (dict, list)):
                cur = cur[wk]; path.append(wk); depth += 1; advanced = True; break
        if advanced: continue

        # Struct
        sk = lk.get("struct")
        if sk and isinstance(cur[sk], (dict, list)):
            cur = cur[sk]; path.append(sk); depth += 1; continue

        break
    return cur, path

# ---------------- locate quest list ----------------
def _quest_root_dict(data: dict) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    root = data.get("root")
    if not isinstance(root, dict): return None, None
    props = root.get("properties")
    if not isinstance(props, dict): return None, None
    # be robust to casing and `_0` suffix variants
    lk = _lkeys(props)
    for key in ("questsavedata_0", "questsavedata", "quest_save_data_0", "quest_save_data"):
        if key in lk:
            return props[lk[key]], lk[key]
    return None, None

def _find_quest_array_and_path_standard(data: dict) -> Tuple[Optional[List[Any]], List[Union[str,int]], str]:
    qsd, qkey = _quest_root_dict(data)
    if not isinstance(qsd, dict): return None, [], "no root"
    path: List[Union[str,int]] = ["root", "properties", qkey]

    cur = qsd
    # descend through possible nested Structs (case-insensitive)
    for _ in range(3):
        if isinstance(cur, dict):
            lk = _lkeys(cur)
            sk = lk.get("struct")
            if sk and isinstance(cur[sk], (dict, list)):
                cur = cur[sk]; path.append(sk)
            else:
                break

    if isinstance(cur, dict):
        lk = _lkeys(cur)
        ql = lk.get("questlist_0") or lk.get("questlist") or lk.get("quests") or lk.get("storyquests")
        if ql and isinstance(cur[ql], dict):
            cur = cur[ql]; path.append(ql)

    if isinstance(cur, dict):
        lk = _lkeys(cur)
        arrk = lk.get("array")
        if arrk and isinstance(cur[arrk], dict):
            path.append(arrk)
            a = cur[arrk]; alk = _lkeys(a)
            if alk.get("struct") and isinstance(a[alk["struct"]], dict):
                sv = a[alk["struct"]]; svlk = _lkeys(sv)
                if svlk.get("value") and isinstance(sv[svlk["value"]], list):
                    path.extend([alk["struct"], svlk["value"]]); return sv[svlk["value"]], path, "Array.Struct.value"
            if alk.get("value") and isinstance(a[alk["value"]], list):
                path.append(alk["value"]); return a[alk["value"]], path, "Array.value"

    u = _unwrap(qsd)
    if isinstance(u, list): return u, path, "generic unwrap"
    return None, [], "no list found"

def _deep_candidate_scan(node: JSON, base: List[Union[str,int]]) -> List[Tuple[List[Union[str,int]], List[Any], str]]:
    hits: List[Tuple[List[Union[str,int]], List[Any], str]] = []
    def looks_like_quest(elem: Any) -> bool:
        e = _unwrap(elem)
        if isinstance(e, dict):
            lk = _lkeys(e)
            for k in ("queststate_0","state","queststate","equeststate","quest_state_0"):
                if k in lk: return True
            for n in ("questcodename_0","questname_0","name","codename","questid_0","questid"):
                if n in lk: return True
        return False

    def walk(n: JSON, p: List[Union[str,int]]):
        if isinstance(n, list) and n:
            sample = n[0]
            if looks_like_quest(sample):
                hits.append((p, n, "deep-scan"))
        if isinstance(n, dict):
            for k, v in n.items():
                walk(v, p + [k])
        elif isinstance(n, list):
            for i, v in enumerate(n):
                walk(v, p + [i])
    walk(node, base)
    return hits

def _find_quest_array_and_path(data: dict) -> Tuple[Optional[List[Any]], List[Union[str,int]], str]:
    lst, path, how = _find_quest_array_and_path_standard(data)
    if isinstance(lst, list) and lst:
        return lst, path, how
    root = data.get("root")
    if not isinstance(root, dict): return None, [], "no root"
    candidates = _deep_candidate_scan(root, ["root"])
    if candidates:
        candidates.sort(key=lambda t: len(t[1]), reverse=True)
        p, l, _ = candidates[0]
        return l, p, "deep-scan"
    return None, [], "no list found"

# ---------------- name/state/progress helpers ----------------
_STATE_KEYS = {"QuestState_0", "State", "QuestState", "ElQuestState", "EQuestState", "Quest_State_0"}
_NAME_KEYS  = {"QuestCodeName_0", "QuestName_0", "Name", "CodeName", "QuestId_0", "QuestID"}

def _dfs_find_key(node: JSON, names: Set[str]) -> Optional[List[Union[str,int]]]:
    stack: List[Tuple[JSON, List[Union[str,int]]]] = [(node, [])]
    names_lc = {n.lower() for n in names}
    while stack:
        cur, p = stack.pop()
        if isinstance(cur, dict):
            lk = _lkeys(cur)
            for want in names_lc:
                if want in lk: return p + [lk[want]]
            for k, v in cur.items(): stack.append((v, p + [k]))
        elif isinstance(cur, list):
            for i, v in enumerate(cur): stack.append((v, p + [i]))
    return None

def _dfs_find_enum_value(node: JSON) -> Optional[List[Union[str,int]]]:
    stack: List[Tuple[JSON, List[Union[str,int]]]] = [(node, [])]
    while stack:
        cur, p = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items(): stack.append((v, p + [k]))
        elif isinstance(cur, list):
            for i, v in enumerate(cur): stack.append((v, p + [i]))
        else:
            if isinstance(cur, str) and ("QuestState::" in cur or cur.startswith("E_")):
                return p
    return None

def _first_string(node: Any, depth: int = 8) -> Optional[str]:
    if depth <= 0: return None
    if isinstance(node, str): return node
    if isinstance(node, dict):
        lk = _lkeys(node)
        for key in ("Name","String","Str","Value","name","value"):
            k = key.lower()
            if k in lk and isinstance(node[lk[k]], str): return node[lk[k]]
        for v in node.values():
            s = _first_string(v, depth-1)
            if s is not None: return s
    if isinstance(node, list):
        for v in node:
            s = _first_string(v, depth-1)
            if s is not None: return s
    return None

def _coerce_name(val: Any) -> str:
    if isinstance(val, str): return val
    return _first_string(val) or ""

def _extract_state_value(node: JSON) -> Any:
    if isinstance(node, dict):
        lk = _lkeys(node)
        if "enum" in lk and isinstance(node[lk["enum"]], (str, int)): return node[lk["enum"]]
        if "name" in lk and isinstance(node[lk["name"]], (str, int)): return node[lk["name"]]
    return node

def _is_intlike(x: Any) -> bool:
    if isinstance(x, bool): return False
    if isinstance(x, int): return True
    if isinstance(x, str):
        s = x.strip()
        if s.startswith(('+','-')): s = s[1:]
        return s.isdigit()
    return False

def _pretty_label_from_path(path: List[Union[str,int]]) -> str:
    """Readable label from last path bits."""
    skip = {"Array","Struct","value","Value","Int","Int32","Int64"}
    parts: List[str] = []
    for tok in path:
        s = str(tok)
        if s in skip: continue
        parts.append(s)
    if not parts: return "value"
    parts = parts[-3:]
    out: List[str] = []
    for p in parts:
        if p.isdigit():
            out[-1] = f"{out[-1]}[{p}]"
        else:
            out.append(p)
    return ".".join(out)

def _path_sig(path: List[Union[str,int]]) -> str:
    return "/".join(str(p) for p in path[-2:]).lower()

def _collect_progress_objects(node: JSON) -> List[Tuple[List[Union[str,int]], str, Any]]:
    """Collect ALL int-like leaves under this quest node (relative paths)."""
    out: List[Tuple[List[Union[str,int]], str, Any]] = []

    def walk(n: JSON, rel: List[Union[str,int]]):
        if isinstance(n, dict):
            lk = _lkeys(n)
            for k, v in n.items():
                key = lk.get(str(k).lower(), k)
                walk(v, rel + [key])
            return
        if isinstance(n, list):
            for i, v in enumerate(n):
                walk(v, rel + [i])
            return
        if _is_intlike(n):
            out.append((rel, _pretty_label_from_path(rel), int(n) if isinstance(n, str) and n.strip().isdigit() else n))

    walk(_unwrap(node), [])
    return out

# ---------------- main discovery ----------------
def discover_quests(data: dict) -> Tuple[List[Dict[str, Any]], List[Tuple[str,int]]]:
    """
    Return rows with absolute paths so we can write back safely.
    Each row:
      - name
      - state (raw)
      - state_path_abs (absolute path to state leaf wrapper)
      - progress_objects: [{path_abs,label,sig,value}]
      - elem_base_abs: absolute path to the unwrapped quest root
    """
    lst, path, how = _find_quest_array_and_path(data)
    if not isinstance(lst, list): return [], []
    debug_meta = [(".".join(str(x) for x in path) + f"  ({how})", len(lst))]
    rows: List[Dict[str, Any]] = []

    for idx, raw_elem in enumerate(lst):
        node, elem_base_unwrapped = _unwrap_with_path(raw_elem, path + [idx])
        state_p_rel = _dfs_find_key(node, _STATE_KEYS) or _dfs_find_enum_value(node)
        name_p_rel  = _dfs_find_key(node, _NAME_KEYS)

        raw_state = _extract_state_value(_get(node, state_p_rel)) if state_p_rel else "Inactive"
        raw_name  = _get(node, name_p_rel) if name_p_rel else None
        name_str  = _coerce_name(raw_name) or _coerce_name(node)

        progress_objects = []
        for rel, label, val in _collect_progress_objects(node):
            abs_path = elem_base_unwrapped + rel
            progress_objects.append({
                "path_abs": abs_path,
                "label": label,
                "sig": _path_sig(abs_path),
                "value": val
            })

        rows.append({
            "name": name_str,
            "state": raw_state if raw_state is not None else "Inactive",
            "state_path_abs": (elem_base_unwrapped + state_p_rel) if state_p_rel else None,
            "progress_objects": progress_objects,
            "elem_base_abs": elem_base_unwrapped,
        })
    return rows, debug_meta

# ---------------- edits ----------------
def _state_leaf_path(obj: JSON, path: List[Union[str,int]]) -> List[Union[str,int]]:
    """Return leaf path that points to Enum/Name/scalar where the quest state actually lives."""
    cur = _get(obj, path)
    if isinstance(cur, dict):
        lk = _lkeys(cur)
        if "enum" in lk:  return path + [lk["enum"]]
        if "name" in lk:  return path + [lk["name"]]
    return path

def apply_quest_edit(
    data: dict,
    row: Dict[str, Any],
    *,
    new_state: Optional[Union[str, int]] = None,
    new_progress: Optional[Any] = None,
    progress_path_override: Optional[List[Union[str,int]]] = None
) -> bool:
    """Write state/progress to the *leaf* that the game reads."""
    changed = False

    # ---- state ----
    if new_state is not None and row.get("state_path_abs"):
        leaf_path = _state_leaf_path(data, row["state_path_abs"])
        cur_leaf = _get(data, leaf_path)
        canon = _norm_enum(str(new_state))
        if isinstance(cur_leaf, str):
            val = _retarget_enum_like(cur_leaf, canon)
        elif isinstance(cur_leaf, int):
            if isinstance(new_state, int):
                val = new_state
            else:
                if "E_INACTIVE" in canon: val = 0
                elif "E_IN_PROGRESS" in canon: val = 1
                elif "E_COMPLETE_SUCCESS" in canon: val = 2
                elif "E_COMPLETE_FAIL" in canon: val = 3
                else: val = cur_leaf
        else:
            val = canon
        changed |= _set(data, leaf_path, val)

    # ---- progress ----
    target_path = progress_path_override
    if target_path is None and row.get("progress_objects"):
        target_path = row["progress_objects"][0].get("path_abs")
    if new_progress is not None and target_path:
        try: ip = int(new_progress)
        except Exception: ip = new_progress
        changed |= _set(data, target_path, ip)

    return changed

# ---------------- import / update + add-missing ----------------
_punct_tbl = str.maketrans("", "", string.punctuation + " _\t\r\n")
def _norm_name(s: str) -> str:
    """Normalize quest names for stable matching: lowercase, strip, drop spaces/underscores/punct."""
    return (s or "").strip().lower().translate(_punct_tbl)

def _dfs_find_int_by_key(obj: JSON, base_path: List[Union[str,int]], key_lower: str) -> Optional[List[Union[str,int]]]:
    """
    DFS under obj at base_path to find an int leaf whose parent dict key matches key_lower.
    Returns absolute path to that int leaf (including inner key if wrapped, e.g., {"Int": 1}).
    """
    root = _get(obj, base_path)
    if root is None:
        return None

    out: Optional[List[Union[str,int]]] = None

    def walk(n: JSON, p: List[Union[str,int]]):
        nonlocal out
        if out is not None:
            return
        if isinstance(n, dict):
            lk = _lkeys(n)
            for k, v in n.items():
                pk = str(k).lower()
                # Exact key match with direct int
                if pk == key_lower and isinstance(v, int):
                    out = p + [lk.get(pk, k)]; return
                # Key match with wrapped int (e.g., {"Int": 1})
                if pk == key_lower and isinstance(v, dict):
                    for inner_k, inner_v in v.items():
                        if isinstance(inner_v, int):
                            out = p + [lk.get(pk, k), inner_k]; return
                # Recurse
                walk(v, p + [lk.get(pk, k)])
            return
        if isinstance(n, list):
            for i, v in enumerate(n):
                walk(v, p + [i])
            return

    walk(root, base_path)
    return out

def _quest_array_ref(data: dict) -> Tuple[Optional[List[Any]], List[Union[str,int]]]:
    """Return (list_ref, absolute_path_to_that_list)."""
    lst, path, _ = _find_quest_array_and_path(data)
    return lst, path

def _build_new_quest_from_template(template_elem: Any, name: str, state_enum: str,
                                   progress_items: List[Dict[str, Any]]) -> Any:
    """
    Create a new quest element by cloning a template element (structure-preserving)
    and patching only name/state/progress ints we can identify. Uses ABSOLUTE paths.
    """
    new_elem = _clone(template_elem)

    # Get the unwrapped node AND its absolute base path inside new_elem
    elem_unwrapped, elem_base_abs = _unwrap_with_path(new_elem, [])

    # ---- set name ----
    name_p_rel = _dfs_find_key(elem_unwrapped, _NAME_KEYS)
    if name_p_rel:
        _set(new_elem, elem_base_abs + name_p_rel, name)

    # ---- set state on the *leaf* (Enum/Name/int) ----
    state_p_rel = _dfs_find_key(elem_unwrapped, _STATE_KEYS) or _dfs_find_enum_value(elem_unwrapped)
    if state_p_rel:
        leaf_abs = _state_leaf_path(new_elem, elem_base_abs + state_p_rel)
        cur = _get(new_elem, leaf_abs)
        canon = _norm_enum(state_enum)
        if isinstance(cur, str):
            _set(new_elem, leaf_abs, _retarget_enum_like(cur, canon))
        elif isinstance(cur, int):
            if   "E_INACTIVE"          in canon: val = 0
            elif "E_IN_PROGRESS"       in canon: val = 1
            elif "E_COMPLETE_SUCCESS"  in canon: val = 2
            elif "E_COMPLETE_FAIL"     in canon: val = 3
            else: val = cur
            _set(new_elem, leaf_abs, val)
        else:
            _set(new_elem, leaf_abs, canon)

    # ---- progress: best-effort write by key label search inside this element ----
    for p in (progress_items or []):
        label_lc = str(p.get("label","")).strip().lower()
        try:
            val = int(p.get("value"))
        except Exception:
            continue
        abs_path = _dfs_find_int_by_key(new_elem, elem_base_abs, label_lc)
        if abs_path is not None:
            _set(new_elem, abs_path, val)

    return new_elem

def replace_quest_by_name_smart(
    data: dict,
    exported_rows: List[dict],
    *,
    add_missing: bool = True
) -> Tuple[int,int]:
    """
    Update existing quests by normalized name. If add_missing=True, append minimal
    new quests built from a template element (structure-preserving) for names not found.
    Progress values are written conservatively (path/label/norm-label/sig/position/deep-search).
    Returns: (quests_updated_count_including_adds, progress_values_set_count)
    """
    cur_rows, _ = discover_quests(data)

    # Build name -> rows map using normalized names (queue duplicates)
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for r in cur_rows:
        nm = _norm_name(r.get("name") or "")
        if nm:
            by_name.setdefault(nm, []).append(r)

    # also need a template to create new quests if requested
    qlist, _qlist_path = _quest_array_ref(data)
    template_elem = None
    if isinstance(qlist, list) and qlist:
        template_elem = qlist[0]  # first quest as structural template

    def nlabel(s: str) -> str:
        return _norm_name(s)

    applied_rows = 0
    applied_prog = 0
    added = 0

    for src in exported_rows:
        raw_name = src.get("name") or ""
        nm = _norm_name(raw_name)
        if not nm:
            continue

        # If quest exists -> update in place
        if nm in by_name and by_name[nm]:
            dst = by_name[nm].pop(0)

            # ---- state ----
            st = src.get("state")
            if st is not None and dst.get("state_path_abs"):
                leaf_path = _state_leaf_path(data, dst["state_path_abs"])
                target = _retarget_enum_like(_get(data, leaf_path), st)
                if _set(data, leaf_path, target):
                    dst["state"] = target
                    applied_rows += 1

            # ---- progress ----
            dst_objs = list(dst.get("progress_objects") or [])
            src_items = list(src.get("progress") or [])
            if src_items:
                by_lab: Dict[str, List[int]] = {}
                by_nlab: Dict[str, List[int]] = {}
                by_sig: Dict[str, List[int]] = {}
                for i, o in enumerate(dst_objs):
                    lab = str(o.get("label",""))
                    by_lab.setdefault(lab, []).append(i)
                    by_nlab.setdefault(nlabel(lab), []).append(i)
                    by_sig.setdefault(str(o.get("sig","")), []).append(i)

                used: Set[int] = set()

                # 1) exact path
                for p in src_items:
                    pth = p.get("path_abs")
                    if isinstance(pth, list):
                        try: val = int(p.get("value"))
                        except Exception: continue
                        if _set(data, pth, val):
                            applied_prog += 1
                            p["__done"] = True

                # 2) exact label
                for p in src_items:
                    if p.get("__done"): continue
                    lab = str(p.get("label",""))
                    if lab in by_lab:
                        lst = by_lab[lab]
                        while lst and lst[0] in used: lst.pop(0)
                        if lst:
                            i = lst.pop(0); used.add(i)
                            try: val = int(p.get("value"))
                            except Exception: continue
                            if _set(data, dst_objs[i]["path_abs"], val):
                                dst_objs[i]["value"] = val; applied_prog += 1
                            p["__done"] = True

                # 3) normalized label
                for p in src_items:
                    if p.get("__done"): continue
                    key = nlabel(str(p.get("label","")))
                    if key in by_nlab:
                        lst = by_nlab[key]
                        while lst and lst[0] in used: lst.pop(0)
                        if lst:
                            i = lst.pop(0); used.add(i)
                            try: val = int(p.get("value"))
                            except Exception: continue
                            if _set(data, dst_objs[i]["path_abs"], val):
                                dst_objs[i]["value"] = val; applied_prog += 1
                            p["__done"] = True

                # 4) signature
                for p in src_items:
                    if p.get("__done"): continue
                    sig = str(p.get("sig",""))
                    if sig and sig in by_sig:
                        lst = by_sig[sig]
                        while lst and lst[0] in used: lst.pop(0)
                        if lst:
                            i = lst.pop(0); used.add(i)
                            try: val = int(p.get("value"))
                            except Exception: continue
                            if _set(data, dst_objs[i]["path_abs"], val):
                                dst_objs[i]["value"] = val; applied_prog += 1
                            p["__done"] = True

                # 5) position fallback
                di = 0
                for p in src_items:
                    if p.get("__done"): continue
                    while di < len(dst_objs) and di in used: di += 1
                    if di >= len(dst_objs): break
                    try: val = int(p.get("value"))
                    except Exception: continue
                    if _set(data, dst_objs[di]["path_abs"], val):
                        dst_objs[di]["value"] = val; applied_prog += 1
                    used.add(di); di += 1
                    p["__done"] = True

                # 6) deep key search within this quest’s subtree (handles index drift / wrapper changes)
                base = dst.get("elem_base_abs")
                if isinstance(base, list):
                    for p in src_items:
                        if p.get("__done"): continue
                        label_lc = str(p.get("label","")).strip().lower()
                        if not label_lc: continue
                        target_abs = _dfs_find_int_by_key(data, base, label_lc)
                        if target_abs is None:
                            continue
                        try: val = int(p.get("value"))
                        except Exception: continue
                        if _set(data, target_abs, val):
                            applied_prog += 1
                        p["__done"] = True

            continue  # done updating this quest

        # If we’re here: quest name not found
        if add_missing and isinstance(qlist, list) and template_elem is not None:
            new_elem = _build_new_quest_from_template(
                template_elem=template_elem,
                name=raw_name,
                state_enum=_norm_enum(src.get("state") or "E_IN_PROGRESS"),
                progress_items=list(src.get("progress") or []),
            )
            qlist.append(new_elem)
            added += 1

            # Register newly added quest
            new_rows, _ = discover_quests(data)
            for r in new_rows:
                if _norm_name(r.get("name") or "") == nm:
                    by_name.setdefault(nm, []).append(r)
                    break

    return applied_rows + added, applied_prog
