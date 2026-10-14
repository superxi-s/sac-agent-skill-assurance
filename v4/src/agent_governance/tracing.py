from dataclasses import dataclass


@dataclass(frozen=True)
class TraceEvent:
    trace_id: str
    stage: str
    outcome: str


class TraceRecorder:
    def __init__(self):
        self.events: list[TraceEvent] = []

    def record(self, trace_id: str, stage: str, outcome: str) -> None:
        self.events.append(TraceEvent(trace_id, stage, outcome))
