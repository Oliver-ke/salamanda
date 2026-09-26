import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
});
