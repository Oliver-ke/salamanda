import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Page from './page';

describe('home page', () => {
  it('renders the expense tracker heading', () => {
    render(<Page />);
    expect(screen.getByRole('heading', { name: /expense tracker/i })).toBeInTheDocument();
  });

  it('shows the subtitle as a paragraph under the heading', () => {
    render(<Page />);
    const subtitle = screen.getByText('Know where your money goes.');
    expect(subtitle).toBeInTheDocument();
    expect(subtitle.tagName).toBe('P');
    const heading = screen.getByRole('heading', { name: /expense tracker/i });
    expect(heading.nextElementSibling).toBe(subtitle);
  });

  it('says there are no expenses yet', () => {
    render(<Page />);
    expect(screen.getByText(/no expenses yet/i)).toBeInTheDocument();
  });
});
