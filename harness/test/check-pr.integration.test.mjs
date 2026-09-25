import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// This suite drives the real check-pr.mjs CLI against a throwaway git
// repository, because the bugs it guards against (git's quoted-path encoding
// of non-ASCII filenames, and rename detection hiding a protected source path)
// live in the seam between git's real output and the pure checkPullRequest()
// logic — unit tests that hand in clean `changedFiles` can never exercise it.

const here = path.dirname(fileURLToPath(import.meta.url));
const checkPrScript = path.join(here, '..', 'src', 'cli', 'check-pr.mjs');
const protectedPathsScript = path.join(here, '..', 'src', 'cli', 'protected-paths.mjs');

// Do not inherit the host machine's git config: in particular this must not
// pick up a `core.quotePath=false` that would mask the bug this suite exists
// to catch.
const gitEnv = {
  ...process.env,
  GIT_CONFIG_GLOBAL: '/dev/null',
  GIT_CONFIG_SYSTEM: '/dev/null',
};

function makeRepo(prefix) {
  const dir = mkdtempSync(path.join(tmpdir(), prefix));
  const git = (args) => execFileSync('git', args, { cwd: dir, env: gitEnv, encoding: 'utf8' });
  git(['init', '-b', 'main']);
  git(['config', 'user.email', 't@t']);
  git(['config', 'user.name', 't']);
  mkdirSync(path.join(dir, 'app', 'src'), { recursive: true });
  writeFileSync(path.join(dir, 'app', 'src', 'page.tsx'), 'export default () => null;\n');
  writeFileSync(path.join(dir, 'CLAUDE.md'), '# Rules for every run\n');
  git(['add', '-A']);
  git(['commit', '-m', 'baseline']);
  git(['checkout', '-b', 'bot-branch']);
  return { dir, git };
}

function runCheckPr(dir, author, body) {
  return spawnSync(process.execPath, [checkPrScript, '--base', 'main', '--author', author], {
    cwd: dir,
    env: { ...gitEnv, PR_BODY: body },
    encoding: 'utf8',
  });
}

describe('check-pr.mjs against a real git repository', () => {
  let repo;

  before(() => {
    repo = makeRepo('pr-rules-integration-');
    // A legitimate app change plus a protected-path change whose filename has
    // a non-ASCII byte — the kind of path `git diff --name-only` (without -z)
    // wraps in C-style quotes with octal escapes.
    writeFileSync(path.join(repo.dir, 'app', 'src', 'page.tsx'), 'export default () => "hi";\n');
    mkdirSync(path.join(repo.dir, '.github', 'workflows'), { recursive: true });
    writeFileSync(path.join(repo.dir, '.github', 'workflows', 'ëvil.yml'), 'on: pull_request\n');
    repo.git(['add', '-A']);
    repo.git(['commit', '-m', 'bot change']);
  });

  after(() => rmSync(repo.dir, { recursive: true, force: true }));

  it('catches a protected path hidden behind a non-ASCII filename', () => {
    const result = runCheckPr(repo.dir, 'claude[bot]', 'Closes #1');
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /\[protected-path\]/);
    // Only appears unescaped when the CLI reads git's raw (-z) output.
    assert.match(result.stderr, /\.github\/workflows\/ëvil\.yml/);
  });

  it('reads the pull request body from PR_BODY', () => {
    const result = runCheckPr(repo.dir, 'claude[bot]', 'no link here');
    assert.match(result.stderr, /\[issue-link\]/);
  });

  it('exits 0 for a human author without enforcing anything', () => {
    const result = runCheckPr(repo.dir, 'Oliver-ke', '');
    assert.equal(result.status, 0);
    assert.match(result.stdout, /human — rules not enforced/);
  });
});

describe('check-pr.mjs on a clean bot change', () => {
  let repo;

  before(() => {
    repo = makeRepo('pr-rules-clean-');
    writeFileSync(path.join(repo.dir, 'app', 'src', 'page.tsx'), 'export default () => "hi";\n');
    repo.git(['add', '-A']);
    repo.git(['commit', '-m', 'bot change']);
  });

  after(() => rmSync(repo.dir, { recursive: true, force: true }));

  it('exits 0 when only app code changes and the body closes one issue', () => {
    const result = runCheckPr(repo.dir, 'loop-sdlc[bot]', 'Closes #1\n\nSays hi.');
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /no violations/);
  });
});

// With git's default rename detection, `git diff --name-only` reports ONLY the
// destination, so moving a protected file to an unprotected path looks like an
// unrelated addition. Only `--no-renames` makes git report the source too.
describe('check-pr.mjs against a rename that hides a protected path', () => {
  let repo;

  before(() => {
    repo = makeRepo('pr-rules-rename-');
    mkdirSync(path.join(repo.dir, 'notes'), { recursive: true });
    repo.git(['mv', 'CLAUDE.md', path.join('notes', 'for-later.md')]);
    repo.git(['commit', '-m', 'bot change: tidy up some notes']);
  });

  after(() => rmSync(repo.dir, { recursive: true, force: true }));

  it('catches a protected file renamed to an unprotected path', () => {
    const result = runCheckPr(repo.dir, 'claude[bot]', 'Closes #1');
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /CLAUDE\.md is a protected path/);
  });
});

describe('protected-paths.mjs', () => {
  it('prints the protected list as JSON, including the agent runner', () => {
    const out = execFileSync(process.execPath, [protectedPathsScript], { encoding: 'utf8' });
    const list = JSON.parse(out);
    assert.ok(Array.isArray(list));
    assert.ok(list.includes('agent/'));
    assert.ok(list.includes('harness/'));
  });
});
