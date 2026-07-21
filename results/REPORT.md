
## neutral-text

| condition | model | tests | engaged | turns | cost $ | LOC +/- (net) | SOLID | restraint | contract |
|---|---|---|---|---|---|---|---|---|---|
| baseline | opus-4-8 | pass | None | 14 | 1.86 | +296/-200 (+96) | 5 | 4 | 5 |
| both | opus-4-8 | pass | {'solidifier': True, 'ponytail': True} | 11 | 1.40 | +200/-147 (+53) | 5 | 5 | 5 |
| ponytail | opus-4-8 | pass | True | 7 | 1.35 | +237/-163 (+74) | 4 | 5 | 5 |
| solidifier | opus-4-8 | pass | True | 14 | 1.60 | +134/-75 (+59) | 5 | 5 | 5 |
| baseline | sonnet-5 | pass | None | 14 | 1.29 | +351/-214 (+137) | 5 | 4 | 5 |
| both | sonnet-5 | pass | {'solidifier': True, 'ponytail': True} | 11 | 1.16 | +322/-209 (+113) | 4 | 4 | 5 |
| ponytail | sonnet-5 | pass | True | 10 | 0.83 | +297/-215 (+82) | 4 | 4 | 5 |
| solidifier | sonnet-5 | pass | True | 23 | 1.33 | +204/-126 (+78) | 4 | 3 | 5 |

## Direction vs baseline (per fixture; > means higher judge score)

- neutral-text / claude-opus-4-8 / solidifier vs baseline: solid: =, restraint: >, contract: =
- neutral-text / claude-opus-4-8 / ponytail vs baseline: solid: <, restraint: >, contract: =
- neutral-text / claude-opus-4-8 / both vs baseline: solid: =, restraint: >, contract: =
- neutral-text / claude-sonnet-5 / solidifier vs baseline: solid: <, restraint: <, contract: =
- neutral-text / claude-sonnet-5 / ponytail vs baseline: solid: <, restraint: =, contract: =
- neutral-text / claude-sonnet-5 / both vs baseline: solid: <, restraint: =, contract: =

Total spend: runs $10.81 + judging $3.59 = $14.40
