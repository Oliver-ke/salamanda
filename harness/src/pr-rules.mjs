import { closedIssuesFrom } from './pr-claim.mjs';
import { isProtectedPath } from './protected.mjs';

const DEFAULT_BOT_AUTHORS = ['claude[bot]', 'github-actions[bot]'];

/**
 * @param {import('../index.d.ts').PullRequestCheckInput} input
 * @returns {{ enforced: boolean, violations: import('../index.d.ts').Violation[] }}
 */
export function checkPullRequest(input) {
  const bots = input.botAuthors ?? DEFAULT_BOT_AUTHORS;
  // Every GitHub App login ends in "[bot]", so this fails CLOSED if the app
  // identity ever changes: an unrecognised bot is still enforced. Matching only
  // the hardcoded list would silently leave every pull request from, say,
  // `loop-sdlc[bot]` unguarded and green.
  const isBot = bots.includes(input.author) || /\[bot\]$/.test(input.author);
  if (!isBot) {
    return { enforced: false, violations: [] };
  }

  const violations = [];
  const add = (rule, message) => violations.push({ rule, message });

  for (const file of input.changedFiles) {
    if (isProtectedPath(file)) {
      add('protected-path', `${file} is a protected path and may not be changed by ${input.author}`);
    }
  }

  // One run does one issue. The body links it with exactly one closing keyword,
  // so merging the pull request closes that issue and nothing else.
  const issues = closedIssuesFrom(input.body ?? '');
  if (issues.length === 0) {
    add('issue-link', 'the pull request body must contain "Closes #N" for the one issue this run did');
  } else if (issues.length > 1) {
    add(
      'issue-link',
      `closes more than one issue (${issues.map((n) => `#${n}`).join(', ')}) — one issue per run`,
    );
  }

  return { enforced: true, violations };
}
