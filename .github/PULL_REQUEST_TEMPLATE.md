## What and why

<!-- What the change does for OxeePhone users, and why. Link the issue if there is one. -->

## How it was checked

<!-- Tests run, calls or test campaigns played, screenshots of the screens changed. -->

## Checklist

- [ ] OxeePhone code lives in `api/brand/`, `ui/src/brand/` or `brand/`; any edit to an upstream (Dograh) file is gated by a `BRAND` flag and listed in `brand/README.md`
- [ ] Tests pass: `pytest tests/brand` (from `api/`, with `api/.env.test`) and `npx vitest run` / `npx tsc --noEmit` (from `ui/`)
- [ ] `brand/CHANGELOG.md` has an entry under "Unreleased" for user-visible changes
- [ ] No secret, `.env` content, API key or caller personal data in the diff, logs or screenshots
- [ ] Screenshots attached for UI changes
