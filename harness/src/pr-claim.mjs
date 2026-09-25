// GitHub's closing keywords: close/closes/closed, fix/fixes/fixed,
// resolve/resolves/resolved, optionally followed by a colon, then an issue as
// #N, owner/repo#N or https://github.com/owner/repo/issues/N. Every form counts
// as issue N, so a second closing reference in any form is caught.
// agent/src/loop_agent/prompts.py CLOSING_REF mirrors this pattern.
const CLOSING =
  /\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+(?:#|[\w.-]+\/[\w.-]+#|https?:\/\/github\.com\/[\w.-]+\/[\w.-]+\/issues\/)(\d+)\b/gi;

/**
 * Which issues a pull request body closes. A run does exactly one issue, and
 * `pr-rules` requires exactly one entry here for a bot-authored pull request.
 * @param {string} body pull request body
 * @returns {number[]} distinct issue numbers, first-seen order
 */
export function closedIssuesFrom(body) {
  return [...new Set([...body.matchAll(CLOSING)].map((match) => Number(match[1])))];
}
