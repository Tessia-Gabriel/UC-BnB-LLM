import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("scale_probe", Path(__file__).resolve().parents[1]/"scripts/scale_probe.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_large_plan():
    jobs = module.plan([500,200,200], [24,48], [100], 30)
    assert len(jobs) == 4
    assert len({j["id"] for j in jobs}) == 4
    assert jobs[-1]["commitment_count"] == 24000
    assert jobs[-1]["original_variable_count"] == 96000


@pytest.mark.parametrize("units,horizons,limit", [([], [24], 30), ([0],[24],30), ([200],[-1],30), ([200],[24],float("nan"))])
def test_bad_plan(units,horizons,limit):
    with pytest.raises(ValueError):
        module.plan(units,horizons,[100],limit)
