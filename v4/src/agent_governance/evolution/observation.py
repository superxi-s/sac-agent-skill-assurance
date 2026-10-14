from .models import EvolutionObservation, ExperienceRecord
from ..fingerprint import fingerprint


def record(observation: EvolutionObservation) -> ExperienceRecord:
    values = dict(observation_id=observation.observation_id,
        category=observation.category, outcome=observation.outcome,
        source_refs=observation.source_refs, split=observation.split,
        high_risk=observation.high_risk,
    )
    return ExperienceRecord(experience_id=fingerprint(values), **values)
