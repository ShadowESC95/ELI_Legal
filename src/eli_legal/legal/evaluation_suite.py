from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    description: str
    run: Callable[[], bool]


class LegalEvaluationSuite:
    def run(self, cases: list[EvalCase]) -> dict[str, bool]:
        return {case.case_id: bool(case.run()) for case in cases}
