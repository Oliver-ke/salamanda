import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { checkPullRequest, isProtectedPath } from '../src/index.mjs';

const bot = (overrides) => ({
  author: 'claude[bot]',
  changedFiles: ['app/src/app/page.tsx'],
  body: 'Closes #7\n\nAdds the expense form.',
  ...overrides,
});

describe('isProtectedPath', () => {
  it('matches directory prefixes', () => {
    assert.equal(isProtectedPath('.github/workflows/ci.yml'), true);
    assert.equal(isProtectedPath('infra/main.tf'), true);
    assert.equal(isProtectedPath('app/tests/acceptance/board.test.tsx'), true);
  });

  it('matches exact files', () => {
    assert.equal(isProtectedPath('CLAUDE.md'), true);
    assert.equal(isProtectedPath('package-lock.json'), true);
  });

  it('protects every agent instruction file, not just the root one', () => {
    assert.equal(isProtectedPath('app/CLAUDE.md'), true);
    assert.equal(isProtectedPath('app/AGENTS.md'), true);
  });

  it('leaves app source writable and protects the agent runner', () => {
    assert.equal(isProtectedPath('app/src/lib/expenses.ts'), false);
    assert.equal(isProtectedPath('app/src/lib/expenses.test.ts'), false);
    assert.equal(isProtectedPath('agent/src/loop_agent/run.py'), true);
    assert.equal(isProtectedPath('agent/prompt.md'), true);
  });

  it('does not match a path that merely starts with a protected name', () => {
    assert.equal(isProtectedPath('app/src/harness-notes.md'), false);
  });

  // A config the agent may ADD is a config it can use to shadow the one it may
  // not EDIT: an added `app/vitest.config.ts` overrides the protected
  // `app/vitest.config.mts` and can drop `tests/**` from `include`, so
  // `app/tests/acceptance/` never runs while `verify` stays green. Every
  // extension each tool resolves must therefore be protected, in use or not.
  it('protects every extension a tool would resolve, not just the one in use', () => {
    for (const shadow of [
      'app/vitest.config.ts',
      'app/vitest.config.cts',
      'app/vitest.config.js',
      'app/vitest.config.cjs',
      'app/vitest.config.mjs',
      'app/vitest.setup.mts',
      'app/vitest.setup.js',
      'app/vitest.setup.mjs',
      'app/tsconfig.json',
      'app/eslint.config.mjs',
      'app/eslint.config.ts',
      'app/eslint.config.js',
      'app/eslint.config.cjs',
      'app/eslint.config.mts',
      'app/eslint.config.cts',
      'app/next.config.ts',
      'app/next.config.js',
      'app/next.config.mjs',
      'app/postcss.config.mjs',
      'app/postcss.config.js',
      '.nvmrc',
    ]) {
      assert.equal(isProtectedPath(shadow), true, `${shadow} must be protected`);
    }
  });

  // A `<stem>.*` entry protects the whole config family by construction, so a
  // tool gaining a new extension nobody enumerated cannot open a shadowing
  // hole — including extensions this list never mentions by name.
  it('protects every config family by stem, at any extension the tool resolves', () => {
    for (const stem of [
      'app/vitest.config',
      'app/vitest.setup',
      'app/eslint.config',
      'app/next.config',
      'app/postcss.config',
    ]) {
      for (const ext of ['ts', 'mts', 'cts', 'js', 'mjs', 'cjs']) {
        assert.equal(isProtectedPath(`${stem}.${ext}`), true, `${stem}.${ext} must be protected`);
      }
    }
    // Previously-missing gaps the enumerated list left open.
    assert.equal(isProtectedPath('app/postcss.config.cts'), true);
    assert.equal(isProtectedPath('app/next.config.mts'), true);
    assert.equal(isProtectedPath('app/vitest.setup.cjs'), true);
  });

  it('does not match a stem entry by prefix instead of extension', () => {
    assert.equal(isProtectedPath('app/vitest.config.d/evil.ts'), false);
    assert.equal(isProtectedPath('app/vitest.config'), false);
  });

  it('protects app/tsconfig.json exactly, not by stem', () => {
    assert.equal(isProtectedPath('app/tsconfig.json'), true);
    assert.equal(isProtectedPath('app/tsconfig.build.json'), false);
  });
});


describe('checkPullRequest', () => {
  it('does not enforce anything for a human author', () => {
    const result = checkPullRequest({
      author: 'Oliver-ke',
      changedFiles: ['.github/workflows/ci.yml', 'harness/src/pr-rules.mjs'],
      body: '',
    });
    assert.equal(result.enforced, false);
    assert.deepEqual(result.violations, []);
  });

  it('enforces the rules for an unrecognised [bot] author', () => {
    const result = checkPullRequest(
      bot({ author: 'loop-sdlc[bot]', changedFiles: ['harness/src/pr-rules.mjs'] }),
    );
    assert.equal(result.enforced, true);
    assert.deepEqual(result.violations.map((v) => v.rule), ['protected-path']);
  });

  it('does not enforce anything for a human login that is not in the bot list', () => {
    const result = checkPullRequest(
      bot({ author: 'some-contributor', changedFiles: ['harness/src/pr-rules.mjs'] }),
    );
    assert.equal(result.enforced, false);
  });

  it('passes a clean bot pull request', () => {
    assert.deepEqual(checkPullRequest(bot()), { enforced: true, violations: [] });
  });

  it('rejects a bot pull request touching a protected path, naming it', () => {
    const result = checkPullRequest(bot({ changedFiles: ['app/src/x.ts', 'CLAUDE.md'] }));
    assert.deepEqual(result.violations.map((v) => v.rule), ['protected-path']);
    assert.match(result.violations[0].message, /CLAUDE\.md is a protected path/);
  });

  it('rejects a bot pull request touching the agent runner', () => {
    const result = checkPullRequest(bot({ changedFiles: ['agent/prompt.md'] }));
    assert.deepEqual(result.violations.map((v) => v.rule), ['protected-path']);
  });

  it('rejects a bot pull request whose body closes no issue', () => {
    const result = checkPullRequest(bot({ body: 'Adds the expense form. Related to #7.' }));
    assert.deepEqual(result.violations.map((v) => v.rule), ['issue-link']);
    assert.match(result.violations[0].message, /Closes #N/);
  });

  it('rejects a bot pull request that closes two issues', () => {
    const result = checkPullRequest(bot({ body: 'Closes #7\nCloses #8' }));
    assert.deepEqual(result.violations.map((v) => v.rule), ['issue-link']);
    assert.match(result.violations[0].message, /#7, #8/);
  });

  it('accepts other closing keywords and a repeated mention of the same issue', () => {
    assert.deepEqual(checkPullRequest(bot({ body: 'Fixes #7. (fixes #7)' })).violations, []);
  });

  it('treats a missing body as closing no issue', () => {
    const result = checkPullRequest(bot({ body: undefined }));
    assert.deepEqual(result.violations.map((v) => v.rule), ['issue-link']);
  });

  it('reports protected-path violations before the issue-link violation', () => {
    const result = checkPullRequest(bot({ changedFiles: ['infra/main.tf'], body: '' }));
    assert.deepEqual(result.violations.map((v) => v.rule), ['protected-path', 'issue-link']);
  });
});
