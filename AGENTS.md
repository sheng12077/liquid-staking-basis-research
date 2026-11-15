# Engineering Workflow

## Git workflow

- Keep `main` limited to completed, conclusive work.
- Use a topic branch prefixed with `feat/`, `fix/`, `exp/`, `research/`,
  `infra/`, `docs/`, or `chore/` for each work segment.
- Merge completed work with `git merge --no-ff`, then delete the topic branch.
- Write commits as `type: description` or `type(scope): description`.
- Stage files explicitly; do not use `git commit -a`.
- Ask before rewriting history or pushing to a remote.

## Experiments

- Register expectations and acceptance thresholds in a standalone commit on
  `main` before implementing or running a performance experiment.
- Do not revise registered thresholds after observing results.
- Data-feasibility pilots must not calculate strategy returns.

## Data and secrets

- Never commit datasets, API keys, credentials, or secrets.
- Keep reusable acquisition and audit code in this repository.
- Store strategy-neutral source data under the shared research data root.

