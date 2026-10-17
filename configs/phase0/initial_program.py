import numpy as np

USED_FEATURES = [9, 43]
PARAMS = [0.5, 0.5]
BOUNDS = [[0.0, 1.0], [0.0, 1.0]]


def score_function(variable_features, params):
    return (
        params[0] * 4 * variable_features[:, 9] * (1 - variable_features[:, 9])
        + params[1] * variable_features[:, 43]
    )
