from __future__ import annotations

import json
from pathlib import Path

from app.strategies.breakout_retest_v2 import (
    FAILURE_DETECTION_AGE_BARS,
    FAILURE_WATCH_MAX_BARS,
    PARAMETERS_VERSION_V2,
)

MANIFEST = Path("config/validation/breakout_retest_v2_holdout.json")


def test_holdout_manifest_matches_frozen_v2_implementation() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rules = payload["frozen_rules"]

    assert payload["strategy_name"] == "BreakoutRetestV2"
    assert payload["implementation_status"] == "implemented_frozen"
    assert payload["strategy_parameters_version"] == PARAMETERS_VERSION_V2
    assert rules["failure_min_position_age_bars"] == FAILURE_DETECTION_AGE_BARS
    assert rules["watch_max_bars"] == FAILURE_WATCH_MAX_BARS
    assert rules["watch_episodes_per_position"] == 1
    assert rules["recovery_precedes_timeout_on_same_bar"] is True
    assert rules["dca_enabled"] is False
    assert rules["future_data_allowed"] is False
