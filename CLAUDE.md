# Rules for every run

You are running unattended in an isolated MicroVM. One run does one GitHub issue and
exits. The worker around you owns git, the pull request and the issue comments; you
edit files and run the allowed commands, then call `finish` or `give_up`.

## Scope
- Do exactly the issue you were given. Never start a second one.
- Before writing code, search the repo to confirm the thing isn't already built.
- If the issue turns out too big for one run, do **not** partially implement it. File
  smaller child issues with `file_child_issue`, then call `give_up` saying why.

## Never touch
`.github/`, `infra/`, `harness/`, `agent/`, `app/tests/acceptance/`, `CLAUDE.md`,
`CODEOWNERS`, `app/CLAUDE.md`, `app/AGENTS.md`, `package.json`, `package-lock.json`,
`app/package.json`, `app/tsconfig.json`, `.nvmrc`, and **every** extension of
`app/vitest.config.*`, `app/vitest.setup.*`, `app/eslint.config.*`,
`app/next.config.*` and `app/postcss.config.*` — including ones that do not exist
yet, because adding a second config would shadow the protected one.
`harness/src/protected.mjs` is the authoritative list. Your file tools refuse these
paths and CI fails any pull request that touches them. If the issue seems to need one
changed, call `give_up` and say so.

If you need a new dependency, you cannot add one. Call `give_up` and say so.

## Definition of done
`npm run verify` passes — typecheck, lint, tests, build — with no test skipped, no
`@ts-expect-error` added, and no assertion weakened. Fix the code, never the check.
Call `finish` only when everything the issue asks for is genuinely true.

## Workflow
- Write the test first, watch it fail, then make it pass.
- Report honestly. `finish` takes a one-line summary of what changed and how you
  verified it. `give_up` is a good outcome when you cannot finish; a false "done" is not.

## Conventions
- App code: TypeScript, Next.js App Router, files under `app/src/`. Unit tests colocated
  as `*.test.ts(x)`.
- Never use `runtime = 'edge'`. The app reads the filesystem.
