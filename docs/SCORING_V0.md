# Sky Score v0

Sky Score v0 is deterministic and explainable. It is not a machine-learning prediction.

## Hard gates

A candidate window is invalid when:

- the Sun is above the target-specific darkness threshold;
- the target is below the local terrain horizon;
- severe cloud cover crosses the configured limit;
- the place is inaccessible or marked unsafe.

## Aggregation

For valid windows, normalized components `s_i ∈ [0,1]` are combined using a weighted geometric mean:

`Q = product(s_i ** w_i)` with `sum(w_i) = 1`.

A geometric mean prevents a strong component such as darkness from fully compensating for a near-zero component such as cloud clearance.

## Components

- cloud clearance;
- darkness;
- transparency proxy;
- Moon conditions;
- humidity/dew margin;
- wind;
- target altitude;
- accessibility;
- forecast confidence.

Weights vary by target and observation mode. Configuration is versioned. Every result returns component values, weights, warnings, and explanation codes.

## Ranking utility

Place ranking may include travel and risk penalties after the physical Sky Score:

`utility = score - distance_penalty - risk_penalty - uncertainty_penalty`.

The API should also expose interpretable alternatives: best quality, nearest acceptable, best balance, and safest.
