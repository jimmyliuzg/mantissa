"""Keep README's minimal configuration executable."""
import json
import re
from pathlib import Path

from retirement_planner.config.validation import validate_config
from retirement_planner.engine import RetirementPlanner


README = Path(__file__).parents[2] / "README.md"


def _read_minimal_config() -> dict:
    text = README.read_text(encoding="utf-8")
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    assert match is not None, "README has no JSON configuration example"
    return json.loads(match.group(1))


def test_readme_minimal_config_validates_and_projects(tmp_path):
    config = _read_minimal_config()
    validation = validate_config(config)
    assert validation.valid, validation.as_dict()

    path = tmp_path / "readme-plan.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    projections = RetirementPlanner.from_config(str(path)).project_cash_flow()
    assert projections
