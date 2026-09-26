import { describe, expect, it } from 'vitest';
import { formatCents } from './format';

describe('formatCents', () => {
  it.each([
    [1250, '$12.50'],
    [5, '$0.05'],
    [100, '$1.00'],
    [0, '$0.00'],
    [123456789, '$1,234,567.89'],
  ])('formats %i cents as %s', (cents, expected) => {
    expect(formatCents(cents)).toBe(expected);
  });
});
