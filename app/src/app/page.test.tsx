import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Page from './page';

describe('home page', () => {
  it('renders the expense tracker heading', () => {
    render(<Page />);
    expect(screen.getByRole('heading', { name: /expense tracker/i })).toBeInTheDocument();
  });

  it('says there are no expenses yet', () => {
    render(<Page />);
    expect(screen.getByText(/no expenses yet/i)).toBeInTheDocument();
  });
});
