# -*- coding: utf-8 -*-
"""Report-content integrity helpers and chip_structure fallback (Issue #589).

These free functions are used both by :class:`GeminiAnalyzer` and by the
pipeline's "agent weak mode" recovery path.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .result import AnalysisResult  # noqa: F401  (used in string annotations)

logger = logging.getLogger(__name__)


def check_content_integrity(result: "AnalysisResult") -> Tuple[bool, List[str]]:
    """
    Check mandatory fields for report content integrity.
    Returns (pass, missing_fields). Module-level for use by pipeline (agent weak mode).
    """
    missing: List[str] = []
    if result.sentiment_score is None:
        missing.append("sentiment_score")
    if not (result.operation_advice or "").strip():
        missing.append("operation_advice")
    if not (result.analysis_summary or "").strip():
        missing.append("analysis_summary")
    dash = result.dashboard or {}
    core = dash.get("core_conclusion") or {}
    if not (core.get("one_sentence") or "").strip():
        missing.append("dashboard.core_conclusion.one_sentence")
    intel = dash.get("intelligence")
    if intel is None or "risk_alerts" not in intel:
        missing.append("dashboard.intelligence.risk_alerts")
    if result.decision_type in ("buy", "hold"):
        battle = dash.get("battle_plan") or {}
        sp = battle.get("sniper_points") or {}
        stop_loss = sp.get("stop_loss")
        if stop_loss is None or (isinstance(stop_loss, str) and not stop_loss.strip()):
            missing.append("dashboard.battle_plan.sniper_points.stop_loss")
    return len(missing) == 0, missing


def apply_placeholder_fill(result: "AnalysisResult", missing_fields: List[str]) -> None:
    """Fill missing mandatory fields with placeholders (in-place). Module-level for pipeline."""
    for field in missing_fields:
        if field == "sentiment_score":
            result.sentiment_score = 50
        elif field == "operation_advice":
            result.operation_advice = result.operation_advice or "待补充"
        elif field == "analysis_summary":
            result.analysis_summary = result.analysis_summary or "待补充"
        elif field == "dashboard.core_conclusion.one_sentence":
            if not result.dashboard:
                result.dashboard = {}
            if "core_conclusion" not in result.dashboard:
                result.dashboard["core_conclusion"] = {}
            result.dashboard["core_conclusion"]["one_sentence"] = (
                result.dashboard["core_conclusion"].get("one_sentence") or "待补充"
            )
        elif field == "dashboard.intelligence.risk_alerts":
            if not result.dashboard:
                result.dashboard = {}
            if "intelligence" not in result.dashboard:
                result.dashboard["intelligence"] = {}
            if "risk_alerts" not in result.dashboard["intelligence"]:
                result.dashboard["intelligence"]["risk_alerts"] = []
        elif field == "dashboard.battle_plan.sniper_points.stop_loss":
            if not result.dashboard:
                result.dashboard = {}
            if "battle_plan" not in result.dashboard:
                result.dashboard["battle_plan"] = {}
            if "sniper_points" not in result.dashboard["battle_plan"]:
                result.dashboard["battle_plan"]["sniper_points"] = {}
            result.dashboard["battle_plan"]["sniper_points"]["stop_loss"] = "待补充"


# ---------- chip_structure fallback (Issue #589) ----------

_CHIP_KEYS: tuple = ("profit_ratio", "avg_cost", "concentration", "chip_health")


def _is_value_placeholder(v: Any) -> bool:
    """True if value is empty or placeholder (N/A, 数据缺失, etc.)."""
    if v is None:
        return True
    if isinstance(v, (int, float)) and v == 0:
        return True
    s = str(v).strip().lower()
    return s in ("", "n/a", "na", "数据缺失", "未知")


def _safe_float(v: Any, default: float = 0.0) -> float:
    """Safely convert to float; return default on failure. Private helper for chip fill."""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        try:
            return default if math.isnan(float(v)) else float(v)
        except (ValueError, TypeError):
            return default
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def _derive_chip_health(profit_ratio: float, concentration_90: float) -> str:
    """Derive chip_health from profit_ratio and concentration_90."""
    if profit_ratio >= 0.9:
        return "警惕"  # 获利盘极高
    if concentration_90 >= 0.25:
        return "警惕"  # 筹码分散
    if concentration_90 < 0.15 and 0.3 <= profit_ratio < 0.9:
        return "健康"  # 集中且获利比例适中
    return "一般"


def _build_chip_structure_from_data(chip_data: Any) -> Dict[str, Any]:
    """Build chip_structure dict from ChipDistribution or dict."""
    if hasattr(chip_data, "profit_ratio"):
        pr = _safe_float(chip_data.profit_ratio)
        ac = chip_data.avg_cost
        c90 = _safe_float(chip_data.concentration_90)
    else:
        d = chip_data if isinstance(chip_data, dict) else {}
        pr = _safe_float(d.get("profit_ratio"))
        ac = d.get("avg_cost")
        c90 = _safe_float(d.get("concentration_90"))
    chip_health = _derive_chip_health(pr, c90)
    return {
        "profit_ratio": f"{pr:.1%}",
        "avg_cost": ac if (ac is not None and _safe_float(ac) != 0.0) else "N/A",
        "concentration": f"{c90:.2%}",
        "chip_health": chip_health,
    }


def fill_chip_structure_if_needed(result: "AnalysisResult", chip_data: Any) -> None:
    """When chip_data exists, fill chip_structure placeholder fields from chip_data (in-place)."""
    if not result or not chip_data:
        return
    try:
        if not result.dashboard:
            result.dashboard = {}
        dash = result.dashboard
        # Use `or {}` rather than setdefault so that an explicit `null` from LLM is also replaced
        dp = dash.get("data_perspective") or {}
        dash["data_perspective"] = dp
        cs = dp.get("chip_structure") or {}
        filled = _build_chip_structure_from_data(chip_data)
        # Start from a copy of cs to preserve any extra keys the LLM may have added
        merged = dict(cs)
        for k in _CHIP_KEYS:
            if _is_value_placeholder(merged.get(k)):
                merged[k] = filled[k]
        if merged != cs:
            dp["chip_structure"] = merged
            logger.info("[chip_structure] Filled placeholder chip fields from data source (Issue #589)")
    except Exception as e:
        logger.warning("[chip_structure] Fill failed, skipping: %s", e)

