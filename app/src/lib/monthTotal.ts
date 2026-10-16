import type { Expense } from './expenses';

/**
 * Sums, in integer cents, the expenses dated in the same calendar month (local time)
 * as `now`. Expenses from any other month or year are ignored.
 */
export function monthTotal(expenses: readonly Expense[], now: Date = new Date()): number {
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const prefix = `${now.getFullYear()}-${month}-`;
  return expenses.reduce(
    (sum, expense) => (expense.date.startsWith(prefix) ? sum + expense.amount : sum),
    0,
  );
}
