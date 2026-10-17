from pathlib import Path
import gzip
import hashlib
import json
import re
import pytest

from ucbranch.public_uc import (
    read, build, validate, to_unitcommitment_solution,
    validate_unitcommitment_solution,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/public_uc"
SPLITS = ROOT / "configs/public_uc_splits.json"


def test_frozen_public_benchmark_splits():
    manifest = json.loads(SPLITS.read_text())
    expected_sizes = {
        "train": 8,
        "validation": 2,
        "test_same_scale": 2,
        "test_large_scale": 7,
        "ood": 9,
    }
    assert {key: len(value) for key, value in manifest["splits"].items()} == expected_sizes
    filenames = [name for split in manifest["splits"].values() for name in split]
    assert len(filenames) == len(set(filenames)) == 28
    assert set(filenames) == set(manifest["sha256"])
    for filename in filenames:
        path = DATA / filename
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["sha256"][filename]
        instance = read(path)
        assert instance.hours == 24 and instance.license and instance.source
        expected_units = 200 if filename.startswith("or-lib") else int(
            re.search(r"_(\d+)g\.json", filename).group(1)
        )
        assert len(instance.units) == expected_units


@pytest.mark.parametrize("filename,n", [
    ("or-lib_200_0_1_w.json.gz", 200),
    ("tejada19_UC_24h_505g.json.gz", 505),
])
def test_read_public_benchmarks(filename, n):
    instance = read(DATA / filename)
    assert instance.hours == 24 and len(instance.demand) == 24
    assert len(instance.reserve) == 24 and len(instance.units) == n
    assert instance.license and instance.source
    assert all(len(g["widths"]) == len(g["slopes"]) == 4 for g in instance.units)
    model = build(instance)
    names = {v.name for v in model.getVars()}
    assert f"u_{n-1}_23" in names and f"q_{n-1}_23_3" in names
    assert model.getNBinVars() == 3*n*24
    model.freeProb()


def test_unsupported_data_is_rejected(tmp_path):
    with gzip.open(DATA / "or-lib_200_0_1_w.json.gz", "rt") as stream:
        raw = json.load(stream)
    raw["Transmission lines"] = {"line": {}}
    target = tmp_path / "unsupported.json"
    target.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="Transmission lines"):
        read(target)


def test_independent_validator_on_solver_solution():
    instance = read(DATA / "or-lib_200_0_1_w.json.gz")
    model = build(instance)
    model.setRealParam("limits/time", 10)
    model.optimize()
    assert model.getNSols() > 0
    values = {v.name: float(model.getVal(v)) for v in model.getVars(transformed=False)}
    assert validate(instance, values) == pytest.approx(model.getObjVal(), abs=1e-3)
    external = to_unitcommitment_solution(instance, values)
    assert validate_unitcommitment_solution(instance, external) == pytest.approx(
        model.getObjVal(), abs=1e-3
    )
    model.freeProb()
