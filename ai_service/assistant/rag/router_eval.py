"""Offline evaluation for the assistant intent router.

Reports overall accuracy, per-intent precision/recall/F1, a confusion matrix, rule-layer
coverage and precision, LLM-layer accuracy and latency, and per-tag slices.

    python -m assistant.rag.router_eval                      # rules + configured LLM
    python -m assistant.rag.router_eval --rules-only         # no LLM; hard cases count as abstain
    python -m assistant.rag.router_eval --model qwen2.5:7B --json reports/router_eval.json
    python -m assistant.rag.router_eval --fail-under 0.9     # non-zero exit for CI gating
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from assistant.llm_client import CompletionResult, build_complete_fn
from assistant.rag.query_router import ROUTER_MAX_TOKENS, Intent, RouterResult, classify_and_rewrite

DEFAULT_CASES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "intent_eval.json"
ABSTAIN = "abstain"
ERROR = "error"

ClassifyFn = Callable[..., RouterResult]


class _Abstain(Exception):
    """Raised by the rules-only stub so LLM-bound cases are scored as abstentions."""


def _abstain_llm(_messages: list[dict[str, Any]]) -> CompletionResult:
    raise _Abstain


def load_cases(path: Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_cases(
    cases: list[dict[str, Any]],
    *,
    complete_fn: Callable[[list[dict[str, Any]]], CompletionResult],
    classify: ClassifyFn = classify_and_rewrite,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        try:
            result = classify(case["question"], history=case.get("history"), complete_fn=complete_fn)
            predicted, source, rules = result.intent.value, result.source, list(result.matched_rules)
        except _Abstain:
            predicted, source, rules = ABSTAIN, ABSTAIN, []
        except RuntimeError:
            # LLM timeout / provider error: keep scoring the rest; counted as a miss.
            predicted, source, rules = ERROR, ERROR, []
        rows.append(
            {
                "id": case.get("id", case["question"]),
                "question": case["question"],
                "expected": case["expected_intent"],
                "predicted": predicted,
                "source": source,
                "via": case.get("via"),
                "tags": case.get("tags", []),
                "matched_rules": rules,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
    return rows


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct * (len(ordered) - 1)))]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [i.value for i in Intent]
    correct = [r for r in rows if r["predicted"] == r["expected"]]

    per_intent: dict[str, dict[str, Any]] = {}
    for label in labels:
        tp = sum(1 for r in rows if r["predicted"] == label and r["expected"] == label)
        fp = sum(1 for r in rows if r["predicted"] == label and r["expected"] != label)
        fn = sum(1 for r in rows if r["predicted"] != label and r["expected"] == label)
        precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
        f1 = (
            round(2 * precision * recall / (precision + recall), 3)
            if precision and recall
            else None
        )
        per_intent[label] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}

    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        confusion[r["expected"]][r["predicted"]] += 1

    rule_rows = [r for r in rows if r["source"] == "rule"]
    llm_rows = [r for r in rows if r["source"] in {"llm", "fallback"}]
    tag_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        for tag in r["tags"]:
            tag_rows[tag].append(r)

    return {
        "n": len(rows),
        "accuracy": _ratio(len(correct), len(rows)),
        "per_intent": per_intent,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "rules": {
            "coverage": _ratio(len(rule_rows), len(rows)),
            "precision": _ratio(sum(r["predicted"] == r["expected"] for r in rule_rows), len(rule_rows)),
            "fired_on_llm_cases": [r["id"] for r in rule_rows if r["via"] == "llm"],
        },
        "llm": {
            "n": len(llm_rows),
            "accuracy": _ratio(sum(r["predicted"] == r["expected"] for r in llm_rows), len(llm_rows)),
            "parse_fallbacks": sum(r["source"] == "fallback" for r in rows),
            "latency_ms_p50": _percentile([r["latency_ms"] for r in llm_rows], 0.5),
            "latency_ms_p95": _percentile([r["latency_ms"] for r in llm_rows], 0.95),
        },
        "abstained": sum(r["source"] == ABSTAIN for r in rows),
        "llm_errors": sum(r["source"] == ERROR for r in rows),
        "by_tag": {
            tag: _ratio(sum(r["predicted"] == r["expected"] for r in tr), len(tr))
            for tag, tr in sorted(tag_rows.items())
        },
        "errors": [
            {k: r[k] for k in ("id", "question", "expected", "predicted", "source", "matched_rules")}
            for r in rows
            if r["predicted"] != r["expected"] and r["source"] != ABSTAIN
        ],
    }


def format_report(summary: dict[str, Any]) -> str:
    lines = [
        f"cases={summary['n']}  accuracy={summary['accuracy']}  abstained={summary['abstained']}"
        f"  llm_errors={summary['llm_errors']}",
        f"rules: coverage={summary['rules']['coverage']}  precision={summary['rules']['precision']}"
        f"  fired_on_llm_cases={summary['rules']['fired_on_llm_cases']}",
        f"llm:   n={summary['llm']['n']}  accuracy={summary['llm']['accuracy']}"
        f"  parse_fallbacks={summary['llm']['parse_fallbacks']}"
        f"  p50={summary['llm']['latency_ms_p50']}ms  p95={summary['llm']['latency_ms_p95']}ms",
        "",
        f"{'intent':<16}{'P':>7}{'R':>7}{'F1':>7}{'n':>5}",
    ]
    for intent, m in summary["per_intent"].items():
        if not m["support"] and m["precision"] is None:
            continue
        fmt = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
        lines.append(f"{intent:<16}{fmt(m['precision']):>7}{fmt(m['recall']):>7}{fmt(m['f1']):>7}{m['support']:>5}")

    predicted_cols = sorted({p for row in summary["confusion"].values() for p in row})
    lines += ["", "confusion (rows=expected, cols=predicted):", " " * 16 + "".join(f"{c[:9]:>10}" for c in predicted_cols)]
    for expected, row in sorted(summary["confusion"].items()):
        lines.append(f"{expected:<16}" + "".join(f"{row.get(c, 0):>10}" for c in predicted_cols))

    if summary["by_tag"]:
        lines += ["", "by tag: " + ", ".join(f"{t}={a}" for t, a in summary["by_tag"].items())]
    if summary["errors"]:
        lines += ["", "errors:"]
        lines += [
            f"  [{e['source']}] {e['id']}: expected={e['expected']} got={e['predicted']}  {e['question']!r}"
            for e in summary["errors"]
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the assistant intent router.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--rules-only", action="store_true", help="Do not call the LLM.")
    parser.add_argument("--model", help="Override ASSISTANT_LLM_MODEL for this run.")
    parser.add_argument("--json", type=Path, help="Write rows + summary to this file.")
    parser.add_argument("--fail-under", type=float, help="Exit 1 if accuracy is below this value.")
    args = parser.parse_args(argv)

    if args.model:
        os.environ["ASSISTANT_LLM_MODEL"] = args.model

    if args.rules_only:
        complete_fn: Callable[[list[dict[str, Any]]], CompletionResult] = _abstain_llm
    else:
        from assistant.config import load_assistant_config

        cfg = load_assistant_config()
        if not cfg.enabled:
            parser.error("Assistant LLM is not configured; use --rules-only or set ASSISTANT_LLM_*.")
        complete_fn = build_complete_fn(cfg, max_tokens=ROUTER_MAX_TOKENS, temperature=0.0)

    rows = run_cases(load_cases(args.cases), complete_fn=complete_fn)
    summary = summarize(rows)
    print(format_report(summary))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.fail_under is not None and (summary["accuracy"] or 0.0) < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
