"""Strict reader and reference MILP for selected UnitCommitment.jl v0.3 data.

Unsupported benchmark components are rejected instead of silently discarded.
The formulation is project-owned; it is not claimed to reproduce every detail
of UnitCommitment.jl's state-of-the-art default formulation.
"""

from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path

from pyscipopt import Model, quicksum


@dataclass(frozen=True)
class PublicInstance:
    name: str
    source: str
    license: str
    hours: int
    demand: tuple
    reserve: tuple
    units: tuple
    bus_name: str
    reserve_name: str | None


def _numbers(value, label, length=None):
    if not isinstance(value, list) or not value or any(
        not isinstance(x, (int, float)) or not math.isfinite(x) for x in value
    ):
        raise ValueError(f"{label} must be a nonempty finite numeric list")
    result = tuple(float(x) for x in value)
    if length is not None and len(result) != length:
        raise ValueError(f"{label} has {len(result)} values, expected {length}")
    return result


def read(path):
    """Read the supported single-bus subset of UnitCommitment.jl v0.3 JSON."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        raw = json.load(stream)
    if raw.get("Parameters", {}).get("Version") != "0.3":
        raise ValueError("only UnitCommitment.jl schema version 0.3 is supported")
    params = raw["Parameters"]
    hours = int(params.get("Time (h)", params.get("Time horizon (h)", 0)))
    if hours <= 0 or params.get("Time step (min)", 60) != 60:
        raise ValueError("the current reader requires positive hourly periods")
    for section in ("Price-sensitive loads", "Transmission lines", "Contingencies"):
        if raw.get(section):
            raise ValueError(f"unsupported nonempty section: {section}")
    buses = raw.get("Buses", {})
    if len(buses) != 1:
        raise ValueError("the current reference formulation requires exactly one bus")
    bus_name, bus = next(iter(buses.items()))
    demand = _numbers(bus["Load (MW)"], "load", hours)
    reserves = raw.get("Reserves", {})
    if len(reserves) > 1:
        raise ValueError("the current reference formulation supports at most one reserve")
    reserve_name = None
    reserve = (0.0,) * hours
    if reserves:
        reserve_name, item = next(iter(reserves.items()))
        if item.get("Type") != "Spinning":
            raise ValueError("only spinning reserve is supported")
        reserve = _numbers(item["Amount (MW)"], "reserve", hours)
    allowed = {
        "Bus", "Production cost curve (MW)", "Production cost curve ($)",
        "Initial status (h)", "Initial power (MW)", "Minimum uptime (h)",
        "Minimum downtime (h)", "Reserve eligibility", "Startup costs ($)",
        "Startup delays (h)", "Ramp up limit (MW)", "Ramp down limit (MW)",
        "Startup limit (MW)", "Shutdown limit (MW)", "Must run?",
    }
    units = []
    for name, unit in raw.get("Generators", {}).items():
        unknown = set(unit) - allowed
        if unknown:
            raise ValueError(f"{name} has unsupported fields: {sorted(unknown)}")
        if unit["Bus"] != bus_name:
            raise ValueError(f"{name} is assigned to an unknown bus")
        points = _numbers(unit["Production cost curve (MW)"], f"{name} MW curve")
        costs = _numbers(unit["Production cost curve ($)"], f"{name} cost curve")
        if len(points) != len(costs) or len(points) < 2:
            raise ValueError(f"{name} requires matching cost curves with >= 2 points")
        widths = tuple(b - a for a, b in zip(points, points[1:]))
        slopes = tuple((b - a) / width for a, b, width in zip(costs, costs[1:], widths))
        if any(width <= 0 for width in widths) or any(
            b + 1e-9 < a for a, b in zip(slopes, slopes[1:])
        ):
            raise ValueError(f"{name} production curve must be increasing and convex")
        startup_costs = tuple(float(x) for x in unit.get("Startup costs ($)", [0.0]))
        startup_delays = tuple(int(x) for x in unit.get("Startup delays (h)", [1]))
        if len(startup_costs) != 1 or len(startup_delays) != 1:
            raise ValueError(f"{name}: multiple startup-cost categories are not yet supported")
        initial_status = int(unit["Initial status (h)"])
        initial_power = float(unit["Initial power (MW)"])
        if initial_status == 0 or not math.isfinite(initial_power):
            raise ValueError(f"{name} has invalid initial conditions")
        eligibility = tuple(unit.get("Reserve eligibility", []))
        if any(product != reserve_name for product in eligibility):
            raise ValueError(f"{name} refers to an unsupported reserve product")
        pmax = points[-1]
        units.append(dict(
            name=name, pmin=points[0], pmax=pmax, widths=widths, slopes=slopes,
            base_cost=costs[0], startup=startup_costs[0],
            up=int(unit.get("Minimum uptime (h)", 1)),
            down=int(unit.get("Minimum downtime (h)", 1)),
            ramp_up=float(unit.get("Ramp up limit (MW)", pmax)),
            ramp_down=float(unit.get("Ramp down limit (MW)", pmax)),
            startup_limit=float(unit.get("Startup limit (MW)", pmax)),
            shutdown_limit=float(unit.get("Shutdown limit (MW)", pmax)),
            initial_status=initial_status, initial_power=initial_power,
            reserve_eligible=reserve_name in eligibility,
            must_run=bool(unit.get("Must run?", False)),
        ))
    if not units:
        raise ValueError("instance has no generators")
    return PublicInstance(
        path.name, raw.get("SOURCE", ""), raw.get("LICENSE", ""), hours,
        demand, reserve, tuple(units), bus_name, reserve_name,
    )


def build(instance, formulation="standard"):
    """Build the selected single-bus MILP.

    ``standard`` follows the package's public feasibility validator. ``ucjl03``
    reproduces the stronger default ramping convention in UnitCommitment.jl
    v0.3, which also constrains production above minimum during transitions.
    """
    if formulation not in {"standard", "ucjl03"}:
        raise ValueError("formulation must be 'standard' or 'ucjl03'")
    m = Model(instance.name)
    m.hideOutput()
    h = instance.hours
    u, y, z, p, r, segment = {}, {}, {}, {}, {}, {}
    for i, g in enumerate(instance.units):
        for t in range(h):
            u[i, t] = m.addVar(name=f"u_{i}_{t}", vtype="B")
            y[i, t] = m.addVar(name=f"y_{i}_{t}", vtype="B")
            z[i, t] = m.addVar(name=f"z_{i}_{t}", vtype="B")
            p[i, t] = m.addVar(name=f"p_{i}_{t}", lb=0)
            if g["reserve_eligible"]:
                r[i, t] = m.addVar(name=f"r_{i}_{t}", lb=0)
            for k, width in enumerate(g["widths"]):
                segment[i, t, k] = m.addVar(name=f"q_{i}_{t}_{k}", lb=0, ub=width)
    objective = []
    for i, g in enumerate(instance.units):
        initial_on = int(g["initial_status"] > 0)
        for t in range(h):
            prev_u = u[i, t - 1] if t else initial_on
            prev_p = p[i, t - 1] if t else g["initial_power"]
            m.addCons(u[i, t] - prev_u == y[i, t] - z[i, t])
            m.addCons(y[i, t] + z[i, t] <= 1)
            m.addCons(p[i, t] == g["pmin"] * u[i, t] + quicksum(
                segment[i, t, k] for k in range(len(g["widths"]))))
            for k, width in enumerate(g["widths"]):
                m.addCons(segment[i, t, k] <= width * u[i, t])
            headroom = r.get((i, t), 0)
            m.addCons(p[i, t] + headroom <= g["pmax"] * u[i, t])
            if formulation == "standard":
                m.addCons(p[i, t] + headroom - prev_p <=
                          g["ramp_up"] * prev_u + g["startup_limit"] * y[i, t])
                m.addCons(prev_p - p[i, t] <=
                          g["ramp_down"] * u[i, t] + g["shutdown_limit"] * z[i, t])
            elif t == 0 and initial_on:
                # UC.jl v0.3 writes these in terms of production above the
                # minimum, and retains the minimum term even when u[0] is 0.
                current_above = p[i, t] - g["pmin"] * u[i, t]
                m.addCons(g["pmin"] + current_above + headroom - prev_p <=
                          g["ramp_up"])
                m.addCons(prev_p - (g["pmin"] + current_above) <=
                          g["ramp_down"])
            elif t > 0:
                previous_above = prev_p - g["pmin"] * prev_u
                current_above = p[i, t] - g["pmin"] * u[i, t]
                m.addCons(current_above + headroom - previous_above <= g["ramp_up"])
                previous_reserve = r.get((i, t - 1), 0)
                m.addCons(previous_above + previous_reserve - current_above <=
                          g["ramp_down"])
            m.addCons(quicksum(y[i, k] for k in range(max(0, t-g["up"]+1), t+1)) <= u[i, t])
            m.addCons(quicksum(z[i, k] for k in range(max(0, t-g["down"]+1), t+1)) <= 1-u[i, t])
            if g["must_run"]:
                m.addCons(u[i, t] == 1)
            objective.extend([g["base_cost"] * u[i, t], g["startup"] * y[i, t]])
            objective.extend(g["slopes"][k] * segment[i, t, k] for k in range(len(g["widths"])))
        if formulation == "ucjl03":
            if initial_on and g["initial_power"] > g["shutdown_limit"]:
                m.addCons(z[i, 0] == 0)
            for t in range(h - 1):
                m.addCons(
                    p[i, t] <= g["pmax"] * u[i, t]
                    - max(0.0, g["pmax"] - g["shutdown_limit"]) * z[i, t + 1]
                )
        remaining = (g["up"] - g["initial_status"] if initial_on
                     else g["down"] + g["initial_status"])
        for t in range(min(h, max(0, remaining))):
            m.addCons(u[i, t] == initial_on)
    for t in range(h):
        m.addCons(quicksum(p[i, t] for i in range(len(instance.units))) == instance.demand[t])
        m.addCons(quicksum(r.get((i, t), 0) for i in range(len(instance.units))) >= instance.reserve[t])
    m.setObjective(quicksum(objective), "minimize")
    return m


def validate(instance, values, tol=1e-4):
    """Independently check a solution produced by :func:`build`."""
    total = 0.0
    for i, g in enumerate(instance.units):
        initial_on = int(g["initial_status"] > 0)
        starts, stops = [], []
        for t in range(instance.hours):
            on, start, stop = (values[f"{prefix}_{i}_{t}"] for prefix in ("u", "y", "z"))
            power = values[f"p_{i}_{t}"]
            previous_on = values[f"u_{i}_{t-1}"] if t else initial_on
            previous_power = values[f"p_{i}_{t-1}"] if t else g["initial_power"]
            assert all(abs(x-round(x)) <= tol for x in (on, start, stop))
            assert abs(on-previous_on-start+stop) <= tol and start+stop <= 1+tol
            starts.append(start); stops.append(stop)
            segment_power = 0.0
            total += g["base_cost"]*on + g["startup"]*start
            for k, width in enumerate(g["widths"]):
                output = values[f"q_{i}_{t}_{k}"]
                assert -tol <= output <= width*on+tol
                segment_power += output
                total += g["slopes"][k]*output
            assert abs(power-g["pmin"]*on-segment_power) <= tol
            reserve = values.get(f"r_{i}_{t}", 0.0)
            assert reserve >= -tol and power+reserve <= g["pmax"]*on+tol
            assert power+reserve-previous_power <= g["ramp_up"]*previous_on+g["startup_limit"]*start+tol
            assert previous_power-power <= g["ramp_down"]*on+g["shutdown_limit"]*stop+tol
            assert sum(starts[max(0,t-g["up"]+1):]) <= on+tol
            assert sum(stops[max(0,t-g["down"]+1):]) <= 1-on+tol
            if g["must_run"]:
                assert on >= 1-tol
        remaining = (g["up"]-g["initial_status"] if initial_on
                     else g["down"]+g["initial_status"])
        for t in range(min(instance.hours,max(0,remaining))):
            assert abs(values[f"u_{i}_{t}"]-initial_on) <= tol
    for t in range(instance.hours):
        assert abs(sum(values[f"p_{i}_{t}"] for i in range(len(instance.units)))-instance.demand[t]) <= tol
        assert sum(values.get(f"r_{i}_{t}",0.0) for i in range(len(instance.units)))+tol >= instance.reserve[t]
    return total


def to_unitcommitment_solution(instance, values):
    """Convert one of our solutions to UnitCommitment.jl's public JSON format."""
    production, production_cost, startup_cost = {}, {}, {}
    is_on, switch_on, switch_off = {}, {}, {}
    reserve_by_unit = {}
    for i, g in enumerate(instance.units):
        name = g["name"]
        production[name] = [values[f"p_{i}_{t}"] for t in range(instance.hours)]
        is_on[name] = [values[f"u_{i}_{t}"] for t in range(instance.hours)]
        switch_on[name] = [values[f"y_{i}_{t}"] for t in range(instance.hours)]
        switch_off[name] = [values[f"z_{i}_{t}"] for t in range(instance.hours)]
        production_cost[name] = []
        startup_cost[name] = []
        for t in range(instance.hours):
            cost = g["base_cost"] * values[f"u_{i}_{t}"]
            cost += sum(
                g["slopes"][k] * values[f"q_{i}_{t}_{k}"]
                for k in range(len(g["widths"]))
            )
            production_cost[name].append(cost)
            startup_cost[name].append(g["startup"] * values[f"y_{i}_{t}"])
        if g["reserve_eligible"]:
            reserve_by_unit[name] = [
                values[f"r_{i}_{t}"] for t in range(instance.hours)
            ]
    spinning = ({instance.reserve_name: reserve_by_unit}
                if instance.reserve_name is not None else {})
    shortfall = ({instance.reserve_name: [0.0] * instance.hours}
                 if instance.reserve_name is not None else {})
    return {
        "Production (MW)": production,
        "Production cost ($)": production_cost,
        "Startup cost ($)": startup_cost,
        "Is on": is_on,
        "Switch on": switch_on,
        "Switch off": switch_off,
        "Net injection (MW)": {instance.bus_name: [0.0] * instance.hours},
        "Load curtail (MW)": {instance.bus_name: [0.0] * instance.hours},
        "Spinning reserve (MW)": spinning,
        "Spinning reserve shortfall (MW)": shortfall,
    }


def validate_unitcommitment_solution(instance, solution, tol=0.02):
    """Check an official UnitCommitment.jl solution using our independent rules."""
    values = {}
    reserve_data = solution.get("Spinning reserve (MW)", {})
    reserve_data = reserve_data.get(instance.reserve_name, {})
    for i, g in enumerate(instance.units):
        name = g["name"]
        for t in range(instance.hours):
            on = float(solution["Is on"][name][t])
            start = float(solution["Switch on"][name][t])
            stop = float(solution["Switch off"][name][t])
            power = float(solution["Production (MW)"][name][t])
            values[f"u_{i}_{t}"] = on
            values[f"y_{i}_{t}"] = start
            values[f"z_{i}_{t}"] = stop
            values[f"p_{i}_{t}"] = power
            if g["reserve_eligible"]:
                values[f"r_{i}_{t}"] = float(reserve_data[name][t])
            residual = max(0.0, power - g["pmin"] * on)
            for k, width in enumerate(g["widths"]):
                output = min(residual, width * on)
                values[f"q_{i}_{t}_{k}"] = output
                residual = max(0.0, residual - output)
    return validate(instance, values, tol=tol)
