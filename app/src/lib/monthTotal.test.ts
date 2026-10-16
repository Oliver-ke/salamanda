import { describe, expect, it } from 'vitest';
import type { Expense } from './expenses';
import { monthTotal } from './monthTotal';

function expense(id: string, date: string, amount: number): Expense {
  return { id, amount, category: 'Food', date, note: '' };
}

// Local time: 15 March 2024, midday.
const now = new Date(2024, 2, 15, 12, 0, 0);

describe('monthTotal', () => {
  it('returns 0 when there are no expenses', () => {
    expect(monthTotal([], now)).toBe(0);
  });

  it('sums only expenses in the current calendar month', () => {
    const expenses = [
      expense('a', '2024-03-01', 1250),
      expense('b', '2024-03-31', 300),
      expense('c', '2024-02-29', 99999),
      expense('d', '2023-03-15', 500),
      expense('e', '2024-04-01', 700),
      expense('f', '2024-03-15', 5),
    ];
    expect(monthTotal(expenses, now)).toBe(1555);
  });

  it('returns 0 when every expense is from another month', () => {
    const expenses = [expense('a', '2024-02-10', 1000), expense('b', '2023-03-10', 2000)];
    expect(monthTotal(expenses, now)).toBe(0);
  });

  it('uses the local calendar month of `now`, zero-padded', () => {
    const nov = new Date(2024, 10, 30, 23, 59, 59);
    const expenses = [expense('a', '2024-11-30', 100), expense('b', '2024-01-30', 200)];
    expect(monthTotal(expenses, nov)).toBe(100);
  });
});
