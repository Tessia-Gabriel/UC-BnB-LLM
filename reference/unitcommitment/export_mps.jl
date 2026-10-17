using UnitCommitment

length(ARGS) == 2 || error("usage: export_mps.jl INSTANCE_JSON OUTPUT_MPS")
instance_path, output_path = ARGS
J = UnitCommitment.JuMP
instance = UnitCommitment.read(instance_path)
model = UnitCommitment.build_model(instance = instance, variable_names = true)

# Match the project's strict power-balance convention. Reserve shortfall is
# already fixed to zero by UnitCommitment.jl when no penalty is configured.
for variable in values(model[:curtail])
    J.fix(variable, 0.0; force = true)
end

mkpath(dirname(output_path))
J.write_to_file(model, output_path)
println(
    "Wrote ", output_path,
    " variables=", J.num_variables(model),
    " constraints=", J.num_constraints(model; count_variable_in_set_constraints = true),
)
