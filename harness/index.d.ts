export declare const PROTECTED_PATHS: readonly string[];
export declare function isProtectedPath(path: string): boolean;

export declare function closedIssuesFrom(body: string): number[];

export interface PullRequestCheckInput {
  author: string;
  botAuthors?: string[];
  changedFiles: string[];
  body?: string;
}

export interface Violation {
  rule: 'protected-path' | 'issue-link';
  message: string;
}

export declare function checkPullRequest(
  input: PullRequestCheckInput,
): { enforced: boolean; violations: Violation[] };
