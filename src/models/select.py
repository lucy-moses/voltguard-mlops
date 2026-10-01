"""Deterministic model-selection rule.

1. Primary metric (default RMSE, lower is better) on the VALIDATION split.
2. Models whose primary metric is within `tie_tolerance` (relative) of the best are 'tied'.
3. Among tied models pick lowest MAE, then highest R2, then lowest primary, then name (stable).
"""
from __future__ import annotations

LOWER_IS_BETTER = {"rmse", "mae", "mse"}


def select_best(candidates: dict[str, dict[str, float]], primary: str = "rmse",
                secondary: tuple[str, ...] | list[str] = ("mae", "r2"),
                tie_tolerance: float = 0.0) -> tuple[str, dict]:
    if not candidates:
        raise ValueError("No candidates to select from")
    if primary not in LOWER_IS_BETTER:
        raise ValueError(f"Primary metric '{primary}' must be lower-is-better")
    best_primary = min(m[primary] for m in candidates.values())
    tied = {n: m for n, m in candidates.items() if m[primary] <= best_primary * (1 + tie_tolerance) + 1e-12}

    def key(name: str) -> tuple:
        m = tied[name]
        sec = tuple(m[s] if s in LOWER_IS_BETTER else -m[s] for s in secondary)
        return (*sec, m[primary], name)

    winner = min(tied, key=key)
    return winner, {"rule": {"primary": primary, "secondary": list(secondary), "tie_tolerance": tie_tolerance},
                    "tied_models": sorted(tied), "winner": winner}
