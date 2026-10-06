# Planted-rule suite (SIM_PLANTED), measured results

200 simulated traders per cell, 300 permutations, 4 proposals in the trial ledger (threshold 0.05/4), run in 578s. Fraction of simulated traders for which:

| scenario | trips | detector flags size habit | court ACCEPTS the cap rule | court says UNDERPOWERED |
|---|---|---|---|---|
| null (no leak) | 60 | 2% | 0% | 100% |
| null (no leak) | 150 | 0% | 0% | 98% |
| null (no leak) | 300 | 0% | 0% | 55% |
| null (no leak) | 600 | 0% | 3% | 2% |
| costless habit (sizes up 3x after a loss, no extra loss) | 60 | 98% | 0% | 100% |
| costless habit (sizes up 3x after a loss, no extra loss) | 150 | 100% | 1% | 2% |
| costless habit (sizes up 3x after a loss, no extra loss) | 300 | 100% | 2% | 0% |
| costless habit (sizes up 3x after a loss, no extra loss) | 600 | 100% | 0% | 0% |
| costly leak (sizes up 3x and does worse after a loss) | 60 | 94% | 0% | 100% |
| costly leak (sizes up 3x and does worse after a loss) | 150 | 100% | 5% | 9% |
| costly leak (sizes up 3x and does worse after a loss) | 300 | 100% | 10% | 0% |
| costly leak (sizes up 3x and does worse after a loss) | 600 | 100% | 28% | 0% |

Reading: on the null the court must accept about 0 percent (false admission). On the costless habit the detector may flag but the court must not accept (a habit that does not cost money is not a leak). On the costly leak, power rises with sample size and is low at small n; that is why UNDERPOWERED is the normal answer at 40-80 trades.
