import { loadExpenses, newestFirst } from '@/lib/expenses';
import { formatCents } from '@/lib/format';

// Expenses are read from the filesystem on every request, never baked in at build time.
export const dynamic = 'force-dynamic';

export default async function Page() {
  const expenses = newestFirst(await loadExpenses());

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-semibold">Expense Tracker</h1>
      <p className="mt-1 text-neutral-600">Know where your money goes.</p>
      {expenses.length === 0 ? (
        <p className="mt-2 text-sm text-neutral-500">No expenses yet.</p>
      ) : (
        <table className="mt-6 w-full text-left text-sm">
          <thead className="border-b text-neutral-500">
            <tr>
              <th scope="col" className="py-2">Date</th>
              <th scope="col" className="py-2">Category</th>
              <th scope="col" className="py-2">Note</th>
              <th scope="col" className="py-2 text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            {expenses.map((expense) => (
              <tr key={expense.id} className="border-b last:border-0">
                <td className="py-2">{expense.date}</td>
                <td className="py-2">{expense.category}</td>
                <td className="py-2">{expense.note}</td>
                <td className="py-2 text-right tabular-nums">{formatCents(expense.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
