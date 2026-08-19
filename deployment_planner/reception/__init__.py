"""Reception providers and the process-wide outline registry."""
from pathlib import Path
from .outline import OutlineStore
from .simulated import SimulatedProvider

RUNTIME_OUTLINES = Path(__file__).resolve().parents[1] / "runtime" / "outlines"
outline_store = OutlineStore(RUNTIME_OUTLINES)
simulated_provider = SimulatedProvider()


def provider_for(receiver):
    if receiver.reception_model == "simulated":return simulated_provider
    if receiver.reception_model == "outline":return outline_store
    raise ValueError(f"Unknown reception provider {receiver.reception_model}")

