// @vitest-environment node
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { GET, POST } from './route';

let dir: string;
const originalEnv = process.env.EXPENSES_FILE;

beforeEach(async () => {
  dir = await mkdtemp(path.join(tmpdir(), 'expenses-route-test-'));
  process.env.EXPENSES_FILE = path.join(dir, 'expenses.json');
});

afterEach(async () => {
  if (originalEnv === undefined) delete process.env.EXPENSES_FILE;
  else process.env.EXPENSES_FILE = originalEnv;
  await rm(dir, { recursive: true, force: true });
});

const valid = { amount: 1250, category: 'Food', date: '2024-03-15', note: 'Lunch' };

function post(body: unknown): Request {
  return new Request('http://localhost/api/expenses', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

describe('GET /api/expenses', () => {
  it('returns an empty list when there are no expenses', async () => {
    const res = await GET();
    expect(res.status).toBe(200);
    await expect(res.json()).resolves.toEqual({ expenses: [] });
  });
});

describe('POST /api/expenses', () => {
  it('creates an expense (201) that GET then returns', async () => {
    const res = await POST(post(valid));
    expect(res.status).toBe(201);
    const created = await res.json();
    expect(created).toMatchObject(valid);
    expect(typeof created.id).toBe('string');

    const list = await (await GET()).json();
    expect(list).toEqual({ expenses: [created] });
  });

  it('GET returns expenses newest date first', async () => {
    const older = await (await POST(post({ ...valid, date: '2024-01-01' }))).json();
    const newest = await (await POST(post({ ...valid, date: '2024-06-30' }))).json();
    const middle = await (await POST(post({ ...valid, date: '2024-03-15' }))).json();

    const list = await (await GET()).json();
    expect(list.expenses).toEqual([newest, middle, older]);
  });

  it.each([
    ['zero', 0],
    ['negative', -5],
    ['non-integer', 12.5],
    ['string', '12'],
  ])('returns 400 naming amount for an invalid amount (%s)', async (_label, amount) => {
    const res = await POST(post({ ...valid, amount }));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(/amount/i);

    await expect((await GET()).json()).resolves.toEqual({ expenses: [] });
  });

  it.each([
    ['category', { category: '' }],
    ['date', { date: '2023-02-29' }],
    ['note', { note: 42 }],
  ])('returns 400 naming %s when it is invalid', async (field, override) => {
    const res = await POST(post({ ...valid, ...override }));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(new RegExp(field, 'i'));
  });

  it('returns 400 for a body that is not valid JSON', async () => {
    const res = await POST(post('{ not json'));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(typeof body.error).toBe('string');
  });

  it('returns 400 for a JSON body that is not an object', async () => {
    const res = await POST(post([valid]));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(typeof body.error).toBe('string');
  });
});
