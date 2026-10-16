import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Expense } from '@/lib/expenses';

const { loadExpenses } = vi.hoisted(() => ({ loadExpenses: vi.fn<() => Promise<Expense[]>>() }));

vi.mock('@/lib/expenses', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/expenses')>();
  return { ...actual, loadExpenses };
});

import Page from './page';

async function renderPage() {
  render(await Page());
}

beforeEach(() => {
  loadExpenses.mockReset();
  loadExpenses.mockResolvedValue([]);
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2024, 2, 20, 12, 0, 0));
});

afterEach(() => {
  vi.useRealTimers();
});

describe('home page', () => {
  it('renders the expense tracker heading', async () => {
    await renderPage();
    expect(screen.getByRole('heading', { name: /expense tracker/i })).toBeInTheDocument();
  });

  it('shows the subtitle as a paragraph under the heading', async () => {
    await renderPage();
    const subtitle = screen.getByText('Know where your money goes.');
    expect(subtitle).toBeInTheDocument();
    expect(subtitle.tagName).toBe('P');
    const heading = screen.getByRole('heading', { name: /expense tracker/i });
    expect(heading.nextElementSibling).toBe(subtitle);
  });

  it('says there are no expenses yet when there are none', async () => {
    await renderPage();
    expect(screen.getByText(/no expenses yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('lists expenses newest first with date, category, note and amount', async () => {
    loadExpenses.mockResolvedValue([
      { id: 'a', amount: 1250, category: 'Food', date: '2024-03-10', note: 'Lunch' },
      { id: 'b', amount: 300, category: 'Transport', date: '2024-03-15', note: 'Bus' },
      { id: 'c', amount: 99999, category: 'Rent', date: '2024-03-01', note: '' },
      { id: 'd', amount: 5, category: 'Snacks', date: '2024-03-15', note: 'Gum' },
    ]);
    await renderPage();

    expect(screen.queryByText(/no expenses yet/i)).not.toBeInTheDocument();
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1);
    const cells = rows.map((row) =>
      within(row)
        .getAllByRole('cell')
        .map((cell) => cell.textContent),
    );
    expect(cells).toEqual([
      ['2024-03-15', 'Snacks', 'Gum', '$0.05'],
      ['2024-03-15', 'Transport', 'Bus', '$3.00'],
      ['2024-03-10', 'Food', 'Lunch', '$12.50'],
      ['2024-03-01', 'Rent', '', '$999.99'],
    ]);
  });

  describe('monthly total', () => {
    it('shows the total of only this calendar month, above the list', async () => {
      loadExpenses.mockResolvedValue([
        { id: 'a', amount: 1250, category: 'Food', date: '2024-03-10', note: 'Lunch' },
        { id: 'b', amount: 10000, category: 'Rent', date: '2024-02-28', note: '' },
        { id: 'c', amount: 11095, category: 'Travel', date: '2024-03-01', note: 'Train' },
        { id: 'd', amount: 700, category: 'Food', date: '2023-03-15', note: 'Last year' },
        { id: 'e', amount: 400, category: 'Food', date: '2024-04-01', note: 'Next month' },
      ]);
      await renderPage();

      const total = screen.getByText('This month: $123.45');
      expect(total).toBeInTheDocument();
      const table = screen.getByRole('table');
      expect(
        total.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });

    it('shows $0.00 when all expenses are from other months', async () => {
      loadExpenses.mockResolvedValue([
        { id: 'a', amount: 1250, category: 'Food', date: '2024-02-10', note: 'Lunch' },
        { id: 'b', amount: 300, category: 'Transport', date: '2023-03-20', note: 'Bus' },
      ]);
      await renderPage();

      expect(screen.getByText('This month: $0.00')).toBeInTheDocument();
      expect(screen.getByRole('table')).toBeInTheDocument();
    });

    it('shows $0.00 when there are no expenses at all', async () => {
      await renderPage();
      expect(screen.getByText('This month: $0.00')).toBeInTheDocument();
    });
  });
});
