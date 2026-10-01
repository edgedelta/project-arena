"""Shared scenario selection for execution and scoring."""
import json
from pathlib import Path
from .smoke import SCENARIOS


def scenarios(suite):
    if suite == "smoke": return SCENARIOS
    if suite == "full":
        return json.loads((Path(__file__).resolve().parents[1] / "scenarios/scenarios.json").read_text())
    raise ValueError("unknown suite: " + str(suite))
