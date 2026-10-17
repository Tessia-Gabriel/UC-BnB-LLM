"""Single-bus deterministic thermal UC with initially-off units."""

from dataclasses import dataclass, asdict
import numpy as np
from pyscipopt import Model, quicksum


@dataclass
class Instance:
    seed: int
    demand: list
    units: list

    def to_dict(self):
        return asdict(self)


def generate(seed, n=5, horizon=8):
    rng = np.random.default_rng(seed)
    units = [
        dict(
            pmin=30.0,
            pmax=float(rng.integers(60, 100)),
            cost=float(rng.integers(15, 25)),
            fixed=float(rng.integers(100, 500)),
            startup=float(rng.integers(500, 2000)),
            ramp=20.0,
            up=3,
            down=2,
        )
        for _ in range(n)
    ]
    capacity = sum(g["pmax"] for g in units)
    demand = [
        float(
            round(
                capacity
                * (0.48 + 0.14 * np.sin(t * np.pi / 4) + rng.uniform(-0.04, 0.04)),
                2,
            )
        )
        for t in range(horizon)
    ]
    return Instance(seed, demand, units)


def build(instance):
    m = Model("uc")
    m.hideOutput()
    n, h = len(instance.units), len(instance.demand)
    u = {
        (i, t): m.addVar(name=f"u_{i}_{t}", vtype="B")
        for i in range(n)
        for t in range(h)
    }
    p = {(i, t): m.addVar(name=f"p_{i}_{t}") for i in range(n) for t in range(h)}
    v = {(i, t): m.addVar(name=f"v_{i}_{t}", ub=1) for i in range(n) for t in range(h)}
    w = {(i, t): m.addVar(name=f"w_{i}_{t}", ub=1) for i in range(n) for t in range(h)}
    for i, g in enumerate(instance.units):
        for t in range(h):
            prev = u[i, t - 1] if t else 0
            power = p[i, t - 1] if t else 0
            m.addCons(u[i, t] - prev == v[i, t] - w[i, t])
            m.addCons(v[i, t] <= u[i, t])
            m.addCons(v[i, t] <= 1 - prev)
            m.addCons(w[i, t] <= prev)
            m.addCons(w[i, t] <= 1 - u[i, t])
            m.addCons(p[i, t] >= g["pmin"] * u[i, t])
            m.addCons(p[i, t] <= g["pmax"] * u[i, t])
            m.addCons(p[i, t] - power <= g["ramp"] * prev + g["pmax"] * v[i, t])
            m.addCons(power - p[i, t] <= g["ramp"] * u[i, t] + g["pmax"] * w[i, t])
            m.addCons(
                quicksum(v[i, k] for k in range(max(0, t - g["up"] + 1), t + 1))
                <= u[i, t]
            )
            m.addCons(
                quicksum(w[i, k] for k in range(max(0, t - g["down"] + 1), t + 1))
                <= 1 - u[i, t]
            )
    for t, d in enumerate(instance.demand):
        m.addCons(quicksum(p[i, t] for i in range(n)) == d)
    m.setObjective(
        quicksum(
            g["cost"] * p[i, t] + g["fixed"] * u[i, t] + g["startup"] * v[i, t]
            for i, g in enumerate(instance.units)
            for t in range(h)
        ),
        "minimize",
    )
    return m


def validate(instance, values, tol=1e-5):
    """Independent schedule checks, including objective reconstruction."""
    total = 0.0
    for t, d in enumerate(instance.demand):
        assert (
            abs(sum(values[f"p_{i}_{t}"] for i in range(len(instance.units))) - d)
            <= tol
        )
    for i, g in enumerate(instance.units):
        prev, power, starts, stops = 0, 0.0, [], []
        for t in range(len(instance.demand)):
            on, dispatch = values[f"u_{i}_{t}"], values[f"p_{i}_{t}"]
            assert abs(on - round(on)) <= tol
            start, stop = max(0, on - prev), max(0, prev - on)
            starts.append(start)
            stops.append(stop)
            assert g["pmin"] * on - tol <= dispatch <= g["pmax"] * on + tol
            assert dispatch - power <= g["ramp"] * prev + g["pmax"] * start + tol
            assert power - dispatch <= g["ramp"] * on + g["pmax"] * stop + tol
            assert sum(starts[max(0, t - g["up"] + 1) :]) <= on + tol
            assert sum(stops[max(0, t - g["down"] + 1) :]) <= 1 - on + tol
            total += g["cost"] * dispatch + g["fixed"] * on + g["startup"] * start
            prev, power = on, dispatch
    return total
