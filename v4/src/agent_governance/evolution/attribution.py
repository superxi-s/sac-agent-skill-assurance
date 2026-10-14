from .models import EvolutionObservation


def attribute(observation: EvolutionObservation) -> str:
    if "infra_error" in observation.tags:
        return "infrastructure"
    if "forbidden_operation" in observation.tags:
        return "safety_boundary"
    if observation.category == "review" and observation.outcome != "success":
        return "review_incomplete"
    return observation.category if observation.outcome != "success" else "success"
