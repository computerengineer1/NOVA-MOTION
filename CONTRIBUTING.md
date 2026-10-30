# Contributing to NOVA MOTION

Thanks for helping make NOVA MOTION better.

## Ways to contribute

- Report reproducible bugs using the [bug report form](https://github.com/computerengineer1/NOVA-MOTION/issues/new?template=bug_report.yml).
- Propose ideas using the [feature request form](https://github.com/computerengineer1/NOVA-MOTION/issues/new?template=feature_request.yml).
- Share a public render or workflow using the [showcase form](https://github.com/computerengineer1/NOVA-MOTION/issues/new?template=showcase.yml).
- Submit focused pull requests with a clear explanation and validation notes.

## Local development checks

Backend (run from the repository root):

    cd backend
    python -m pip install -r requirements.txt -r requirements-dev.txt
    python -m pytest -q

Frontend:

    cd frontend
    npm ci
    npm run typecheck
    npm test
    npm run build

## Keep the repository healthy

- Do not commit model weights, generated videos, caches, local databases or build environments.
- Never commit API keys, access tokens, passwords, private logs or personal machine paths.
- Respect the upstream licenses for model weights, runtimes and third-party assets.
- Keep changes focused and update docs when behavior, requirements or setup steps change.
- Include screenshots or short recordings when changing the interface.

All contributions are reviewed before merging. A pull request is not considered verified merely because a workflow was added; the relevant checks must pass.
