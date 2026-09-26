const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

/** Formats integer cents as dollars, e.g. `1250` → `$12.50`. */
export function formatCents(cents: number): string {
  return dollars.format(cents / 100);
}
