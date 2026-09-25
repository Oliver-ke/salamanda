import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { closedIssuesFrom } from '../src/pr-claim.mjs';

describe('closedIssuesFrom', () => {
  it('reads a Closes line', () => {
    assert.deepEqual(closedIssuesFrom('Closes #7\n\nAdds the form.'), [7]);
  });

  it('accepts every GitHub closing keyword, any case, with or without a colon', () => {
    for (const body of ['close #3', 'closes #3', 'Closed #3', 'fix #3', 'Fixes #3', 'fixed #3',
      'resolve #3', 'Resolves #3', 'resolved #3', 'Closes: #3']) {
      assert.deepEqual(closedIssuesFrom(body), [3], body);
    }
  });

  it('ignores a bare mention that is not a closing keyword', () => {
    assert.deepEqual(closedIssuesFrom('Follow-up to #12. See also #13.'), []);
  });

  it('returns every distinct issue closed, in order, once each', () => {
    assert.deepEqual(closedIssuesFrom('Closes #4, fixes #9, closes #4'), [4, 9]);
  });

  it('does not match a keyword embedded in a longer word', () => {
    assert.deepEqual(closedIssuesFrom('prefixes #5 and encloses #6'), []);
  });

  it('returns [] for an empty body', () => {
    assert.deepEqual(closedIssuesFrom(''), []);
  });
});
