import { randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

/** A single recorded expense. `amount` is in integer cents. */
export type Expense = {
  id: string;
  /** Integer cents, > 0. */
  amount: number;
  /** Non-empty. */
  category: string;
  /** `YYYY-MM-DD`. */
  date: string;
  /** May be empty. */
  note: string;
};

export type ExpenseInput = Omit<Expense, 'id'>;

/** Thrown by `addExpense` when the input is invalid. `field` names the offending field. */
export class ExpenseValidationError extends Error {
  readonly field: keyof ExpenseInput;

  constructor(field: keyof ExpenseInput, message: string) {
    super(message);
    this.name = 'ExpenseValidationError';
    this.field = field;
  }
}

/** Path of the expenses file: `EXPENSES_FILE`, else `data/expenses.json` relative to the app. */
function expensesFile(): string {
  const configured = process.env.EXPENSES_FILE;
  return configured && configured.length > 0
    ? path.resolve(configured)
    : path.join(process.cwd(), 'data', 'expenses.json');
}

function isValidDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const d = new Date(Date.UTC(year, month - 1, day));
  return (
    d.getUTCFullYear() === year && d.getUTCMonth() === month - 1 && d.getUTCDate() === day
  );
}

function validate(input: ExpenseInput): void {
  if (typeof input.amount !== 'number' || !Number.isInteger(input.amount) || input.amount <= 0) {
    throw new ExpenseValidationError(
      'amount',
      `Invalid amount: must be a positive integer number of cents, got ${input.amount}`,
    );
  }
  if (typeof input.category !== 'string' || input.category.trim() === '') {
    throw new ExpenseValidationError('category', 'Invalid category: must be a non-empty string');
  }
  if (!isValidDate(input.date)) {
    throw new ExpenseValidationError(
      'date',
      `Invalid date: must be a real calendar date in YYYY-MM-DD format, got "${input.date}"`,
    );
  }
  if (typeof input.note !== 'string') {
    throw new ExpenseValidationError('note', 'Invalid note: must be a string');
  }
}

/**
 * Returns a new array ordered newest date first; among equal dates the later-added
 * (later in the input) comes first. Does not mutate the input.
 */
export function newestFirst(expenses: readonly Expense[]): Expense[] {
  return [...expenses]
    .reverse()
    .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}

/** Reads all expenses. A missing file means no expenses; malformed contents throw naming the file. */
export async function loadExpenses(): Promise<Expense[]> {
  const file = expensesFile();
  let raw: string;
  try {
    raw = await readFile(file, 'utf8');
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw err;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new Error(`Malformed JSON in expenses file ${file}: ${(err as Error).message}`);
  }
  if (!Array.isArray(parsed)) {
    throw new Error(`Expenses file ${file} must contain a JSON array`);
  }
  return parsed as Expense[];
}

/** Validates the input, assigns an id, appends it to the file and returns the stored expense. */
export async function addExpense(input: ExpenseInput): Promise<Expense> {
  validate(input);
  const expense: Expense = {
    id: randomUUID(),
    amount: input.amount,
    category: input.category,
    date: input.date,
    note: input.note,
  };

  const file = expensesFile();
  const expenses = await loadExpenses();
  expenses.push(expense);

  await mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(tmp, JSON.stringify(expenses, null, 2) + '\n', 'utf8');
  await rename(tmp, file);
  return expense;
}
