"""分析表自动选择：LL(1) → LR(0) → SLR(1) → LALR(1) → LR(1)。"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .cfg import Grammar, load_grammar
from .ll1 import LL1Table, build_ll1_table
from .lr import ParseTableSet, build_lr_tables

ParseMethod = str  # LL1 | LR0 | SLR1 | LALR1 | LR1

METHOD_ORDER: List[str] = ["LL1", "LR0", "SLR1", "LALR1", "LR1"]
# 按优先级递增尝试，找到无冲突表即停止，避免无谓构建 LR(1)
SELECT_ORDER: List[str] = ["LL1", "LR0", "SLR1", "LALR1", "LR1"]
CACHE_VERSION = 2


@dataclass
class SelectedParser:
    method: str
    ll1: Optional[LL1Table] = None
    lr: Optional[ParseTableSet] = None
    all_reports: Dict[str, List[str]] = field(default_factory=dict)


def _cache_path(grammar_path: Path) -> Path:
    return grammar_path.parent / ".parse_tables_cache.pkl"


def _build_one(grammar: Grammar, name: str) -> object:
    if name == "LL1":
        return build_ll1_table(grammar)
    return build_lr_tables(grammar, name)


def _analyze_all(grammar_path: Path) -> Tuple[Grammar, Dict[str, object]]:
    cache = _cache_path(grammar_path)
    mtime = grammar_path.stat().st_mtime
    if cache.exists():
        try:
            with open(cache, "rb") as f:
                payload = pickle.load(f)
            if payload.get("mtime") == mtime and payload.get("version") == CACHE_VERSION:
                return payload["grammar"], payload["reports"]
        except Exception:
            pass

    grammar = load_grammar(grammar_path)
    reports: Dict[str, object] = {}

    for name in SELECT_ORDER:
        if name == "LALR1":
            slr = reports.get("SLR1")
            if not isinstance(slr, ParseTableSet) or not slr.conflicts:
                continue
        if name == "LR1":
            lalr = reports.get("LALR1")
            if not isinstance(lalr, ParseTableSet) or not lalr.conflicts:
                continue

        reports[name] = _build_one(grammar, name)
        if not reports[name].conflicts:
            break

    try:
        with open(cache, "wb") as f:
            pickle.dump(
                {"version": CACHE_VERSION, "mtime": mtime, "grammar": grammar, "reports": reports},
                f,
            )
    except Exception:
        pass
    return grammar, reports


@lru_cache(maxsize=2)
def _analyze_cached(grammar_path_str: str) -> Tuple[Grammar, Dict[str, object]]:
    return _analyze_all(Path(grammar_path_str))


def select_parse_method(
    grammar_path: Optional[Path] = None,
    prefer: str = "auto",
) -> SelectedParser:
    path = grammar_path or Path(__file__).parent.parent.parent / "grammar" / "grammar.json"
    grammar, reports = _analyze_cached(str(path))

    all_reports: Dict[str, List[str]] = {}
    for name, obj in reports.items():
        all_reports[name] = list(obj.conflicts)

    if prefer != "auto" and prefer in METHOD_ORDER:
        if prefer not in reports and prefer in ("LALR1", "LR1"):
            reports[prefer] = _build_one(grammar, prefer)
            all_reports[prefer] = list(reports[prefer].conflicts)
        obj = reports[prefer]
        if prefer == "LL1":
            return SelectedParser(prefer, ll1=obj, all_reports=all_reports)
        return SelectedParser(prefer, lr=obj, all_reports=all_reports)

    for name in METHOD_ORDER:
        if name not in reports:
            continue
        obj = reports[name]
        if not obj.conflicts:
            if name == "LL1":
                return SelectedParser(name, ll1=obj, all_reports=all_reports)
            return SelectedParser(name, lr=obj, all_reports=all_reports)

    available = [n for n in METHOD_ORDER if n in reports]
    best = min(
        available,
        key=lambda n: (len(reports[n].conflicts), -METHOD_ORDER.index(n)),
    )
    obj = reports[best]
    if best == "LL1":
        return SelectedParser(best, ll1=obj, all_reports=all_reports)
    return SelectedParser(best, lr=obj, all_reports=all_reports)


def get_parse_tables(grammar_path: Optional[Path] = None) -> Dict[str, object]:
    path = grammar_path or Path(__file__).parent.parent.parent / "grammar" / "grammar.json"
    _, reports = _analyze_cached(str(path))
    return dict(reports)
