using UnitCommitment, HiGHS

length(ARGS) == 4 || error(
    "usage: solve.jl INSTANCE SOLUTION_JSON METRICS_JSON TIME_LIMIT_SECONDS",
)
instance_path, solution_path, metrics_path = ARGS[1:3]
time_limit = parse(Float64, ARGS[4])
time_limit > 0 || error("time limit must be positive")

J = UnitCommitment.JuMP
instance = UnitCommitment.read(instance_path)
optimizer = J.optimizer_with_attributes(
    HiGHS.Optimizer,
    "output_flag" => false,
    "time_limit" => time_limit,
    "mip_rel_gap" => 1e-6,
    "random_seed" => 0,
    "threads" => 1,
)
build_start = time()
model = UnitCommitment.build_model(instance = instance, optimizer = optimizer)
build_seconds = time() - build_start

# UC.jl permits expensive load shedding by default. Our model enforces exact
# balance, so fix shedding to zero before comparing the two formulations.
for variable in values(model[:curtail])
    J.fix(variable, 0.0; force = true)
end

# For the selected single-bus data there are no network constraints to add
# lazily, so direct JuMP optimization is equivalent and respects our time limit.
J.optimize!(model)
J.has_values(model) || error("official model did not find a feasible solution")
solution = UnitCommitment.solution(model)
valid = UnitCommitment.validate(instance, solution)
UnitCommitment.write(solution_path, solution)

reserve_shortfall = sum(
    sum(series) for series in values(solution["Spinning reserve shortfall (MW)"])
)
curtailment = sum(sum(series) for series in values(solution["Load curtail (MW)"]))
metrics = Dict(
    "implementation" => "UnitCommitment.jl",
    "unitcommitment_version" => "0.3.0",
    "solver" => "HiGHS 1.25.4",
    "instance" => basename(instance_path),
    "units" => length(instance.units),
    "hours" => instance.time,
    "status" => string(J.termination_status(model)),
    "objective" => J.objective_value(model),
    "bound" => J.objective_bound(model),
    "gap" => J.relative_gap(model),
    "nodes" => J.node_count(model),
    "build_seconds" => build_seconds,
    "solver_seconds" => J.solve_time(model),
    "official_validator" => valid,
    "load_curtailment_mw" => curtailment,
    "reserve_shortfall_mw" => reserve_shortfall,
    "comparison_adjustment" => "load curtailment fixed to zero",
)
UnitCommitment.write(metrics_path, metrics)
println("Wrote ", solution_path, " and ", metrics_path)
