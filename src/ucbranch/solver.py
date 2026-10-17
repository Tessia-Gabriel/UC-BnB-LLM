"""All methods use the same UC formulation and SCIP settings."""

import time
import numpy as np
import ecole
from ucbranch.uc import build, validate
from ucbranch.integration import normalize


def solve(instance, method="default", score=None, features=None, params=None, limit=60):
    m = build(instance)
    settings = {
        "limits/time": float(limit),
        "randomization/randomseedshift": 0,
        "randomization/permutationseed": 0,
        "parallel/maxnthreads": 1,
    }
    m.setParams(settings)
    original_names = [v.name for v in m.getVars()]
    decisions = 0
    candidate_example = []
    begin = time.perf_counter()
    if method == "default":
        m.optimize()
    else:
        if method == "pseudocost":
            observations = ecole.observation.Pseudocosts()
        else:
            selected = [9] if method == "most_fractional" else features
            node, khalil = (
                ecole.observation.NodeBipartiteFlash(),
                ecole.observation.Khalil2016Flash(),
            )
            node.set_active_features([f for f in selected if f < 19])
            khalil.set_active_features([f - 19 for f in selected if f >= 19])
            observations = {"node": node, "khalil": khalil}
        env = ecole.environment.Branching(
            observation_function=observations, scip_params=settings
        )
        env.seed(0)
        obs, actions, _, done, _ = env.reset(ecole.scip.Model.from_pyscipopt(m))
        m = env.model.as_pyscipopt()
        while not done:
            # SCIPgetVars is ordered by problem index; getIndex() is the distinct
            # creation index and cannot index the Ecole action set after presolve.
            names = {j: v.name for j, v in enumerate(m.getVars(transformed=True))}
            for action in actions:
                assert names[int(action)].removeprefix("t_").startswith("u_"), names[
                    int(action)
                ]
            if not candidate_example:
                candidate_example = [
                    {"action": int(a), "variable": names[int(a)]} for a in actions
                ]
            if method == "pseudocost":
                scores = obs[actions]
            else:
                x = np.concatenate(
                    [
                        obs["node"].variable_features[actions],
                        obs["khalil"].features[actions],
                    ],
                    axis=1,
                )
                if method == "most_fractional":
                    scores = np.minimum(x[:, 9], 1 - x[:, 9])
                else:
                    scores = np.asarray(score(normalize(x, features), params))
            if scores.shape != (len(actions),) or not np.isfinite(scores).all():
                raise ValueError("score_function must return finite candidate scores")
            obs, actions, _, done, _ = env.step(actions[int(np.argmax(scores))])
            decisions += 1
    status = str(m.getStatus())
    result = dict(
        method=method,
        seed=instance.seed,
        status=status,
        nodes=int(m.getNNodes()),
        time=time.perf_counter() - begin,
        solver_time=m.getSolvingTime(),
        decisions=decisions,
        candidate_example=candidate_example,
        settings=settings,
        validity=status == "optimal",
    )
    if m.getNSols():
        # Ecole copies the original model on reset; original variables remain accessible.
        values = {v.name: float(m.getVal(v)) for v in m.getVars(transformed=False)}
        assert set(original_names) == set(values)
        result.update(
            objective=float(m.getObjVal()),
            primal=float(m.getPrimalbound()),
            dual=float(m.getDualbound()),
            gap=float(m.getGap()),
            values=values,
        )
        reconstructed = validate(instance, values)
        assert abs(reconstructed - result["objective"]) < 1e-4
    return result
