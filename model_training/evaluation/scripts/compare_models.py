"""
Compare the existing Traditional ML and fine-tuned Hugging Face evaluation reports.

Default input files:
  model_training/evaluation/results/ml/evaluation.txt
  model_training/evaluation/results/huggingface/evaluation.txt

Default output:
  model_training/evaluation/results/model_comparison.txt

Run from anywhere:
  python model_training/evaluation/scripts/compare_models.py

Optional paths:
  python model_training/evaluation/scripts/compare_models.py --ml-report PATH --hf-report PATH --output PATH

This script only compares the supplied evaluation reports. It does not train models
or change the active model configuration.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path


TASKS = ("Intent", "Priority", "Escalation Risk")


def read_report(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Evaluation report not found: {path}")
    return path.read_text(encoding="utf-8")


def extract_task_metrics(report: str, report_name: str) -> dict:
    metrics = {}

    for task in TASKS:
        pattern = (
            rf"^\s*{re.escape(task)}:\s*Accuracy\s*([\d.]+)%"
            rf"\s*\|\s*Macro-F1\s*([\d.]+)%"
        )
        match = re.search(pattern, report, flags=re.IGNORECASE | re.MULTILINE)
        if not match:
            raise ValueError(
                f"Could not find '{task}' accuracy and Macro-F1 in {report_name}."
            )

        metrics[task] = {
            "accuracy": float(match.group(1)),
            "macro_f1": float(match.group(2)),
        }

    metrics["average_macro_f1"] = sum(
        metrics[task]["macro_f1"] for task in TASKS
    ) / len(TASKS)

    return metrics


def extract_urgent_recall(report: str) -> float | None:
    # Matches the priority class-wise line, e.g.:
    # urgent: P 50.0% | R 75.0% | F1 60.0% | Support 4
    match = re.search(
        r"^\s*urgent:\s*P\s*[\d.]+%\s*\|\s*R\s*([\d.]+)%",
        report,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return float(match.group(1)) if match else None


def extract_latency_note(report: str, is_ml: bool) -> str:
    if is_ml:
        match = re.search(
            r"Average Latency Per Record.*?:\s*([\d.]+)\s*ms",
            report,
            flags=re.IGNORECASE,
        )
        if match:
            return f"{match.group(1)} ms/record (preprocessed features; TF-IDF transform excluded)"
    else:
        match = re.search(
            r"Total Inference Time:\s*([\d.]+)\s*seconds"
            r"\s*\(([\d.]+)\s*ms/record\)",
            report,
            flags=re.IGNORECASE,
        )
        if match:
            return (
                f"{match.group(2)} ms/record "
                f"(tokenization included; model loading excluded)"
            )
    return "Not available"


def build_comparison(ml_report: str, hf_report: str) -> str:
    ml = extract_task_metrics(ml_report, "Traditional ML report")
    hf = extract_task_metrics(hf_report, "Hugging Face report")

    lines = [
        "MODEL COMPARISON",
        "=" * 56,
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "TEST-SET PERFORMANCE",
        "-" * 56,
        f"{'Task':<20}{'Traditional ML':>17}{'Fine-tuned MuRIL':>19}",
        "-" * 56,
    ]

    for task in TASKS:
        lines.append(
            f"{task:<20}"
            f"{ml[task]['macro_f1']:>16.2f}%"
            f"{hf[task]['macro_f1']:>18.2f}%"
        )

    lines.extend([
        "-" * 56,
        f"{'Average Macro-F1':<20}"
        f"{ml['average_macro_f1']:>16.2f}%"
        f"{hf['average_macro_f1']:>18.2f}%",
        "",
        "BEST RESULT BY TASK",
        "-" * 56,
    ])

    for task in TASKS:
        ml_score = ml[task]["macro_f1"]
        hf_score = hf[task]["macro_f1"]
        winner = "Traditional ML" if ml_score > hf_score else (
            "Fine-tuned MuRIL" if hf_score > ml_score else "Tie"
        )
        lines.append(f"{task}: {winner}")

    overall_winner = (
        "Traditional ML"
        if ml["average_macro_f1"] > hf["average_macro_f1"]
        else "Fine-tuned MuRIL"
        if hf["average_macro_f1"] > ml["average_macro_f1"]
        else "Tie"
    )

    lines.extend([
        "",
        f"Best average Macro-F1 on these test reports: {overall_winner}",
        "",
        "URGENT PRIORITY CHECK",
        "-" * 56,
    ])

    ml_urgent = extract_urgent_recall(ml_report)
    hf_urgent = extract_urgent_recall(hf_report)

    lines.append(
        f"Traditional ML urgent recall: "
        f"{ml_urgent:.2f}%" if ml_urgent is not None
        else "Traditional ML urgent recall: Not available"
    )
    lines.append(
        f"Fine-tuned MuRIL urgent recall: "
        f"{hf_urgent:.2f}%" if hf_urgent is not None
        else "Fine-tuned MuRIL urgent recall: Not available"
    )

    lines.extend([
        "",
        "LATENCY (NOT DIRECTLY COMPARABLE)",
        "-" * 56,
        f"Traditional ML: {extract_latency_note(ml_report, is_ml=True)}",
        f"Fine-tuned MuRIL: {extract_latency_note(hf_report, is_ml=False)}",
        "",
    ])

    # Dynamically determine the current implementation candidate.
    task_wins = {"Traditional ML": [], "Fine-tuned MuRIL": []}
    for task in TASKS:
        ml_score = ml[task]["macro_f1"]
        hf_score = hf[task]["macro_f1"]
        if ml_score > hf_score:
            task_wins["Traditional ML"].append(task)
        elif hf_score > ml_score:
            task_wins["Fine-tuned MuRIL"].append(task)

    if overall_winner == "Tie":
        decision_lines = [
            "Current implementation candidate: No clear winner",
            "Use validation results and operational requirements to decide.",
        ]
    else:
        decision_lines = [
            f"Current implementation candidate: {overall_winner}",
            f"Reason: highest average Macro-F1 "
            f"({max(ml['average_macro_f1'], hf['average_macro_f1']):.2f}%).",
        ]
        if task_wins[overall_winner]:
            decision_lines.append(
                "Higher Macro-F1 on: " + ", ".join(task_wins[overall_winner]) + "."
            )

    ml_urgent = extract_urgent_recall(ml_report)
    hf_urgent = extract_urgent_recall(hf_report)
    if ml_urgent is not None and hf_urgent is not None:
        decision_lines.append(
            f"Urgent priority recall: ML {ml_urgent:.2f}% vs "
            f"MuRIL {hf_urgent:.2f}%."
        )

    lines.extend([
        "",
        "CURRENT IMPLEMENTATION DECISION",
        "-" * 56,
        *decision_lines,
        "",
        "This recommendation is calculated dynamically from these reports.",
        "Because these reports use the held-out test set, this is a provisional",
        "code-integration candidate. Confirm the active model using validation",
        "results before deployment; reserve the test set for final evaluation.",
        "",
    ])

    return "\n".join(lines)


def main() -> None:
    script_path = Path(__file__).resolve()
    project_root = script_path.parents[3] if len(script_path.parents) > 3 else script_path.parent

    parser = argparse.ArgumentParser(
        description="Compare Traditional ML and fine-tuned Hugging Face results."
    )
    parser.add_argument(
        "--ml-report",
        type=Path,
        default=project_root / "model_training/evaluation/results/ml/evaluation.txt",
        help="Path to the Traditional ML evaluation.txt",
    )
    parser.add_argument(
        "--hf-report",
        type=Path,
        default=project_root / "model_training/evaluation/results/huggingface/evaluation.txt",
        help="Path to the Hugging Face evaluation.txt",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "model_training/evaluation/results/model_comparison.txt",
        help="Where to save the comparison report",
    )
    args = parser.parse_args()

    ml_text = read_report(args.ml_report)
    hf_text = read_report(args.hf_report)
    comparison = build_comparison(ml_text, hf_text)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(comparison, encoding="utf-8")

    print(comparison)
    print(f"Saved comparison report to: {args.output}")


if __name__ == "__main__":
    main()
