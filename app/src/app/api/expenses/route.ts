import {
  addExpense,
  ExpenseValidationError,
  loadExpenses,
  newestFirst,
  type ExpenseInput,
} from '@/lib/expenses';

// The expenses store lives on the filesystem, so this must run on Node.
export const runtime = 'nodejs';

/** Lists all expenses, newest date first (later-added first among equal dates). */
export async function GET(): Promise<Response> {
  const expenses = newestFirst(await loadExpenses());
  return Response.json({ expenses });
}

/** Creates an expense from `{ amount, category, date, note }`. */
export async function POST(request: Request): Promise<Response> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: 'Invalid body: must be valid JSON' }, { status: 400 });
  }
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return Response.json({ error: 'Invalid body: must be a JSON object' }, { status: 400 });
  }

  const { amount, category, date, note } = body as Record<string, unknown>;
  try {
    const expense = await addExpense({ amount, category, date, note } as ExpenseInput);
    return Response.json(expense, { status: 201 });
  } catch (err) {
    if (err instanceof ExpenseValidationError) {
      return Response.json({ error: err.message }, { status: 400 });
    }
    throw err;
  }
}
