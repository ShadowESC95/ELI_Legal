from eli_legal.domain.enums import RunStatus
from eli_legal.domain.models import Run


class RunService:
    def hold(self, run: Run, reason: str) -> Run:
        run.status = RunStatus.HELD
        if reason not in run.hard_gate_reasons:
            run.hard_gate_reasons.append(reason)
        return run

    def restart_after_authorisation(self, run: Run, *, authorised: bool) -> Run:
        if not authorised:
            raise PermissionError("restart requires recorded authorisation")
        run.hard_gate_reasons.clear()
        run.status = RunStatus.RUNNING
        return run
