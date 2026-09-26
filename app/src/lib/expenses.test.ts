// @vitest-environment node
import { mkdtemp, rm, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { addExpense, ExpenseValidationError, loadExpenses } from './expenses';

let dir: string;
let file: string;
const originalEnv = process.env.EXPENSES_FILE;

beforeEach(async () => {
  dir = await mkdtemp(path.join(tmpdir(), 'expenses-test-'));
  file = path.join(dir, 'expenses.json');
  process.env.EXPENSES_FILE = file;
});

afterEach(async () => {
  if (originalEnv === undefined) delete process.env.EXPENSES_FILE;
  else process.env.EXPENSES_FILE = originalEnv;
  await rm(dir, { recursive: true, force: true });
});

const valid = { amount: 1250, category: 'Food', date: '2024-03-15', note: 'Lunch' };

describe('loadExpenses', () => {
  it('returns [] when the file does not exist', async () => {
    await expect(loadExpenses()).resolves.toEqual([]);
  });

  it('throws an error naming the file when the JSON is malformed', async () => {
    await writeFile(file, '{ not json', 'utf8');
    await expect(loadExpenses()).rejects.toThrow(file);
  });
});

describe('addExpense', () => {
  it('round-trips: add then load returns the expense', async () => {
    const added = await addExpense(valid);
    expect(added).toMatchObject(valid);
    expect(typeof added.id).toBe('string');
    expect(added.id.length).toBeGreaterThan(0);

    await expect(loadExpenses()).resolves.toEqual([added]);
  });

  it('appends and assigns distinct ids', async () => {
    const a = await addExpense(valid);
    const b = await addExpense({ ...valid, amount: 99, note: '' });
    expect(a.id).not.toBe(b.id);
    await expect(loadExpenses()).resolves.toEqual([a, b]);
    const raw = JSON.parse(await readFile(file, 'utf8'));
    expect(raw).toHaveLength(2);
  });

  it('creates missing parent directories', async () => {
    const nested = path.join(dir, 'nested', 'deeper', 'expenses.json');
    process.env.EXPENSES_FILE = nested;
    const added = await addExpense(valid);
    await expect(loadExpenses()).resolves.toEqual([added]);
  });

  it.each([
    ['zero amount', { amount: 0 }],
    ['negative amount', { amount: -5 }],
    ['non-integer amount', { amount: 12.5 }],
    ['NaN amount', { amount: Number.NaN }],
  ])('rejects %s', async (_label, override) => {
    await expect(addExpense({ ...valid, ...override })).rejects.toThrow(/amount/i);
    await expect(loadExpenses()).resolves.toEqual([]);
  });

  it.each([
    ['empty category', { category: '' }],
    ['whitespace-only category', { category: '   ' }],
  ])('rejects %s', async (_label, override) => {
    await expect(addExpense({ ...valid, ...override })).rejects.toThrow(/category/i);
    await expect(loadExpenses()).resolves.toEqual([]);
  });

  it.each([
    ['wrong format', { date: '15/03/2024' }],
    ['missing zero padding', { date: '2024-3-5' }],
    ['impossible month', { date: '2024-13-01' }],
    ['impossible day', { date: '2023-02-29' }],
    ['empty', { date: '' }],
  ])('rejects a bad date (%s)', async (_label, override) => {
    await expect(addExpense({ ...valid, ...override })).rejects.toThrow(/date/i);
    await expect(loadExpenses()).resolves.toEqual([]);
  });

  it.each([
    ['amount', { amount: 0 }],
    ['category', { category: '' }],
    ['date', { date: 'nope' }],
    ['note', { note: 42 as unknown as string }],
  ])('throws an ExpenseValidationError whose field is %s', async (field, override) => {
    const err = await addExpense({ ...valid, ...override }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ExpenseValidationError);
    expect((err as ExpenseValidationError).field).toBe(field);
  });

  it('accepts a leap day in a leap year', async () => {
    await expect(addExpense({ ...valid, date: '2024-02-29' })).resolves.toMatchObject({
      date: '2024-02-29',
    });
  });

  it('accepts an empty note', async () => {
    await expect(addExpense({ ...valid, note: '' })).resolves.toMatchObject({ note: '' });
  });
});
