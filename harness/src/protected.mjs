/**
 * Paths a bot-authored pull request may never change. An entry ending in "/"
 * matches by prefix; an entry ending in ".*" matches "<stem>.<ext>" for any
 * single extension (no "/" in it); everything else matches the exact
 * repo-relative path.
 *
 * `agent/` IS here: it is the agent's own runner — its prompt, its tool
 * sandbox and the code that decides what reaches a pull request. An agent that
 * can edit its runner can widen its own permissions. `app/src/` is not here,
 * including colocated unit tests: the agent needs to write tests for the code
 * it writes. `app/tests/acceptance/` IS here, and that is the anti-cheating net
 * — tests a human wrote that the agent cannot weaken.
 *
 * ## Why config families are protected by stem, not by enumerated extension
 *
 * Protecting a config by its exact current path is one-extension-deep and can
 * be *shadowed*: a config the agent is allowed to ADD is a config it can use to
 * override the one it is not allowed to EDIT. Vitest, ESLint, Next and PostCSS
 * all resolve their config by trying a list of extensions, so leaving
 * `app/vitest.config.mts` protected while `app/vitest.config.ts` is writable
 * lets the agent commit a second Vitest config that drops `tests/**` from
 * `include` — `app/tests/acceptance/` then never runs and `verify` stays green
 * forever. Enumerating every extension a tool resolves closes that hole today
 * but reopens it the moment a tool adds a new extension nobody thought to add
 * to this list. A `<stem>.*` entry protects the whole family by construction:
 * it covers extensions that do not exist yet, so a tool gaining one cannot
 * open a hole here.
 *
 * `app/tsconfig.json` is an exact path, not a stem: `tsc` only ever auto-loads
 * that one filename, so there is no family to shadow. It and the ESLint config
 * are CI configuration in the same sense: `"strict": false` or
 * `export default []` neuters two of the four legs of `npm run verify`.
 * `.nvmrc` selects the Node version both CI jobs run on.
 *
 * When adding a tool with a resolvable config, protect it by `<stem>.*`. This
 * file is the authoritative list; CLAUDE.md, README.md and CODEOWNERS mirror
 * it for humans.
 */
export const PROTECTED_PATHS = [
  '.github/',
  'infra/',
  'harness/',
  'agent/',
  'app/tests/acceptance/',
  'CLAUDE.md',
  'CODEOWNERS',
  'app/CLAUDE.md',
  'app/AGENTS.md',
  'package.json',
  'package-lock.json',
  'app/package.json',
  // Vitest config — any extension Vitest resolves, present or future.
  'app/vitest.config.*',
  // Vitest setup file, likewise.
  'app/vitest.setup.*',
  // Typecheck configuration. Exact path: tsc only auto-loads this filename.
  'app/tsconfig.json',
  // ESLint flat config — any extension eslint resolves, present or future.
  'app/eslint.config.*',
  // Build configuration.
  'app/next.config.*',
  'app/postcss.config.*',
  // The Node version both CI jobs run on.
  '.nvmrc',
];

/** @param {string} path repo-relative, forward slashes */
export function isProtectedPath(path) {
  const normalised = path.replace(/^\.\//, '');
  return PROTECTED_PATHS.some((entry) => {
    if (entry.endsWith('/')) return normalised.startsWith(entry);
    if (entry.endsWith('.*')) {
      const stem = entry.slice(0, -2);
      if (!normalised.startsWith(`${stem}.`)) return false;
      const ext = normalised.slice(stem.length + 1);
      return ext.length > 0 && !ext.includes('/');
    }
    return normalised === entry;
  });
}
