from types import SimpleNamespace

import numpy as np

from calculations_cell import cell_propagation, _print_cell_propagation_audit


def test_cell_propagation_audit_prints_active_counts_and_flowrate(capsys):
    inputs = SimpleNamespace(
        cells=4,
        modules=2,
        units=1,
        cell_volume=1.0,
        total_duration=10.0,
        time_step=1.0,
    )

    result = cell_propagation(inputs, time_array=np.arange(0.0, 11.0, 1.0))
    _print_cell_propagation_audit(result)

    captured = capsys.readouterr().out
    assert "Cell/Module propagation audit" in captured
    assert "active_cells" in captured
    assert "active_modules" in captured
    assert "flowrate" in captured
    assert "0.0" in captured
