using UnitCommitment

length(ARGS) == 2 || error("usage: validate.jl INSTANCE SOLUTION_JSON")
valid = UnitCommitment.validate(ARGS[1], ARGS[2])
println("UnitCommitment.jl validator: ", valid)
valid || exit(1)
