"""Load tunable parameters from params.yml.

One import (`from config import PARAMS`) gives every script the same config, so
there is a single place to change Elo settings, model features, the split
windows, and XGBoost hyperparameters.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARAMS_PATH = PROJECT_ROOT / "params.yml"


def load_params() -> dict:
    """Parse params.yml into a nested dict."""
    with open(PARAMS_PATH) as f:
        return yaml.safe_load(f)


PARAMS = load_params()
