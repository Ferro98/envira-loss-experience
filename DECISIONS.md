Started: 2026-09-23 10:20 CEST
Stopped: 

## What I built

- `GET /portfolios/{id}/loss-experience` (core) and `GET /portfolios/loss-experience`, ordered by loss ratio, worst first: it shows where pricing is wrong regardless of size, and portfolios are of similar size (882–1,072 policies). Ranking by absolute result (premium − loss) gives the same top 7 and the same last.
- An explicit data policy (see README): 815 of 4,509 claims excluded and reported, never dropped silently.
- Verification: `scripts/check_totals.py` recomputes every figure independently and matches the service. It checks the implementation, not the policy choices, which I checked against the data separately. Tests cover each data rule; Docker compose to run it.

## What I deliberately did not build, and why

- No database: ~20k rows are loaded once at startup, so a DB adds infrastructure without changing any answer.

## What I would do first with another day

- Ask Envira about the negative paid amounts (likely sign errors) and the `POL-9xxxxx` orphan claims: both move the loss ratio (overall 0.692; 0.737 if the negatives were sign-flipped).
- A GitHub Actions workflow that runs the tests and builds the Docker image on every push.

AI tools: Claude Code for exploration, code and tests. I rejected its first choice of flipping negative paid amounts to positive (a guess about someone else's data) and excluded them instead. When PF-03's fire loss ratio came out at 3.15, I checked it was not a currency error before accepting it.
