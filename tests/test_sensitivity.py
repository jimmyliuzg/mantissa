from unittest.mock import MagicMock
from retirement_planner.sensitivity import SensitivityAnalyzer


def test_sensitivity_analyzer_init():
    mock_planner = MagicMock()
    analyzer = SensitivityAnalyzer(mock_planner)
    assert analyzer.planner is mock_planner


def test_sensitivity_returns_dict_per_value():
    mock_planner = MagicMock()
    mock_planner.run_single_simulation.return_value = {
        "success": True, "final_net_worth": 2_000_000, "out_of_savings_year": None,
    }
    mock_planner.scenario.economic.get_rate.return_value = {"general_inflation": 0.025}

    analyzer = SensitivityAnalyzer(mock_planner)
    results = analyzer.run(
        variable="investment_return_mean",
        values=[0.05, 0.06, 0.07, 0.08],
        num_simulations=10,
    )
    assert len(results) == 4
    assert all("value" in r for r in results)
    assert all("success_rate" in r for r in results)


def test_sensitivity_formats_output():
    mock_planner = MagicMock()
    mock_planner.run_single_simulation.return_value = {
        "success": True, "final_net_worth": 2_000_000, "out_of_savings_year": None,
    }
    mock_planner.scenario.economic.get_rate.return_value = {"general_inflation": 0.025}

    analyzer = SensitivityAnalyzer(mock_planner)
    results = analyzer.run(
        variable="inflation",
        values=[0.02, 0.03],
        num_simulations=10,
    )
    assert results[0]["variable"] == "inflation"
    assert "success_rate" in results[0]
    assert "avg_final_nw" in results[0]
