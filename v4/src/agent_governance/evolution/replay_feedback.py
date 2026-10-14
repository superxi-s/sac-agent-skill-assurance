import argparse
import json
from pathlib import Path

from .feedback import HumanReviewFeedback, ReviewFeedbackCollector
from .review_quality import ReviewQualityReport


def main():
    parser = argparse.ArgumentParser(description="重放私下匿名质量报告或人工反馈，不自动生成或晋升候选")
    parser.add_argument("input", type=Path)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()
    collector = ReviewFeedbackCollector(args.private_output)
    count = 0
    for line in args.input.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if "task_id" in raw:
            collector.collect(ReviewQualityReport.model_validate_json(line))
        else:
            collector.human_feedback(HumanReviewFeedback.model_validate_json(line))
        count += 1
    print(json.dumps({"replayed": count, "states": collector.states(), "candidate_generated": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
