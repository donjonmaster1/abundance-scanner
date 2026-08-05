"""Tracks estimated LLM spend so actual cost against the <$100/year budget is
visible and auditable (see CLAUDE.md "Cost tracking"), not just assumed.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

# USD per 1M tokens. Standard (non-introductory) pricing, checked 2026-08-05.
PRICING = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
}

COST_LOG_PATH = Path(__file__).resolve().parent.parent / "state" / "cost_log.csv"


@dataclass
class CostTracker:
    calls: list[dict] = field(default_factory=list)

    def record(self, model: str, input_tokens: int, output_tokens: int) -> float:
        rates = PRICING[model]
        cost = (input_tokens / 1_000_000) * rates["input"] + (output_tokens / 1_000_000) * rates["output"]
        self.calls.append(
            {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
            }
        )
        return cost

    @property
    def total_cost(self) -> float:
        return sum(c["cost_usd"] for c in self.calls)

    def write_run_summary(self, run_date: str, path: Path = COST_LOG_PATH) -> None:
        """Append one row per model used this run, plus the running grand total."""
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists()

        by_model: dict[str, dict] = {}
        for c in self.calls:
            entry = by_model.setdefault(c["model"], {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
            entry["input_tokens"] += c["input_tokens"]
            entry["output_tokens"] += c["output_tokens"]
            entry["cost_usd"] += c["cost_usd"]

        running_total = 0.0
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
                if rows:
                    running_total = float(rows[-1]["running_total_usd"])

        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(
                    ["run_date", "model", "input_tokens", "output_tokens", "cost_usd", "running_total_usd"]
                )
            for model, entry in by_model.items():
                running_total += entry["cost_usd"]
                writer.writerow(
                    [
                        run_date,
                        model,
                        entry["input_tokens"],
                        entry["output_tokens"],
                        f"{entry['cost_usd']:.6f}",
                        f"{running_total:.6f}",
                    ]
                )
