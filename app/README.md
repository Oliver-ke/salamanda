# Expense Tracker

A small expense tracker built with Next.js (App Router), TypeScript and Tailwind CSS. It stores expenses in
a JSON file on disk. It shows them newest first, along with how much you've spent this month. Expenses are
added through a JSON HTTP API.

This app is the project the [Salamanda loop](../README.md) builds. Most changes reach it as pull requests
generated from GitHub issues.

## Contents

- [Requirements](#requirements)
- [Running the app](#running-the-app)
- [Using the app](#using-the-app)
- [HTTP API](#http-api)
- [Where the data lives](#where-the-data-lives)
- [Development](#development)
- [Not yet implemented](#not-yet-implemented)

## Requirements

- **Node.js 24** or newer (the version is pinned in the repository's `.nvmrc`; run `nvm use` from the root).
- **npm**, which comes with Node. The repository is an npm workspace, so install from the **repository root**.

## Running the app

From the repository root:

```bash
npm ci                                 # install dependencies for every workspace
npm run dev --workspace app            # start the dev server with hot reload
```

Open <http://localhost:3000>.

For a production build:

```bash
npm run build --workspace app
npm run start --workspace app          # serves the build on http://localhost:3000
```

You can also run the same scripts from inside `app/` (`cd app && npm run dev`).

## Using the app

### The page

`/` shows:

- **This month**: the total of every expense dated in the current calendar month, in US dollars. "Current
  month" uses the **server's** local time zone.
- **The expense table**: date, category, note and amount. It lists the newest date first. When two expenses
  share a date, the one added later comes first.
- **"No expenses yet."** when nothing has been recorded.

The page reads the data file on every request, so a reload shows newly added expenses straight away.

### Adding an expense

There's no form in the UI yet (see [Not yet implemented](#not-yet-implemented)). For now, add expenses by
sending a `POST` to the API while the server is running:

```bash
curl -X POST http://localhost:3000/api/expenses \
  -H 'content-type: application/json' \
  -d '{"amount": 1250, "category": "Food", "date": "2024-03-15", "note": "Lunch"}'
```

Reload the page and the expense appears. **Amounts are in integer cents**, so `1250` is `$12.50`.

### Listing expenses

```bash
curl http://localhost:3000/api/expenses
```

### Editing or removing an expense

The API can't do this yet. Stop the server, edit the data file by hand (see
[Where the data lives](#where-the-data-lives)), keep it a valid JSON array, then start the server again.

## HTTP API

All bodies are JSON.

### `GET /api/expenses`

Returns every expense, in the same order as the page (newest date first).

```json
{
  "expenses": [
    { "id": "3f0c…", "amount": 1250, "category": "Food", "date": "2024-03-15", "note": "Lunch" }
  ]
}
```

### `POST /api/expenses`

Creates an expense. Body fields:

| Field | Type | Rule |
|---|---|---|
| `amount` | number | A positive **integer** number of cents (`1250` = $12.50). `0`, negatives, decimals and strings are rejected. |
| `category` | string | Must not be empty or only whitespace. Free text: there's no fixed list. |
| `date` | string | A real calendar date in `YYYY-MM-DD` format (`2023-02-29` is rejected). |
| `note` | string | Required, but it may be empty (`""`). |

Responses:

| Status | When | Body |
|---|---|---|
| `201 Created` | The expense was saved | The stored expense, including its generated `id` (a UUID) |
| `400 Bad Request` | The body isn't valid JSON, isn't a JSON object, or a field is invalid | `{ "error": "…" }`. For a field error, the message names the field. |

## Where the data lives

Expenses are stored as a JSON array in a single file:

- By default the file is `data/expenses.json`, relative to the directory the server runs in. With the
  commands above, that's `app/data/expenses.json`.
- Set **`EXPENSES_FILE`** to use another path, for example
  `EXPENSES_FILE=/tmp/expenses.json npm run dev --workspace app`.
- If the file doesn't exist, the app treats it as "no expenses". The file and its directory are created on
  the first `POST`.
- If the file holds invalid JSON, or JSON that isn't an array, the page and the API fail with a server
  error. The error message names the file. In production it appears only in the server log.
- Writes go to a temporary file first and are then renamed into place, so a crash can't leave a
  half-written file.

`app/data/` isn't in `.gitignore`, so take care not to commit your personal data.

## Development

The app needs a filesystem, so it runs on the Node.js runtime. Never set `runtime = 'edge'`.

| Path | What it is |
|---|---|
| `src/app/page.tsx` | The home page: this month's total and the expense table |
| `src/app/api/expenses/route.ts` | `GET` and `POST /api/expenses` |
| `src/lib/expenses.ts` | The `Expense` type, validation, sorting, and reading and writing the data file |
| `src/lib/monthTotal.ts` | Sums the expenses in the current calendar month |
| `src/lib/format.ts` | Formats cents as US dollars |

Unit tests sit next to the code as `*.test.ts(x)` and run with Vitest. Human-written acceptance tests go
in `tests/acceptance/`, which the agent isn't allowed to change. Checks, from the repository root:

```bash
npm run verify                                         # typecheck, lint, all tests, build
npm run test --workspace app                           # app tests only
npm run test --workspace app -- src/lib/format.test.ts # a single test file
```

To ask for a change, open a GitHub issue and add the `agent:ready` label (see
[Writing issues](../docs/issues.md)).

## Not yet implemented

These common expense-tracker features don't exist yet. Each would make a good issue for the loop.

**Managing expenses**

- An **add-expense form** on the page. Today the only way to add an expense is the API.
- **Editing** an expense (`PUT`/`PATCH /api/expenses/:id`, plus UI).
- **Deleting** an expense (`DELETE /api/expenses/:id`, plus UI).
- **Recurring expenses** (rent, subscriptions).

**Finding and summarising**

- **Filtering and search** by date range, category or note text.
- **Browsing other months.** Only the current month's total is shown.
- **Totals per category**, plus charts (by category or over time).
- **Budgets** per month or per category, with a warning when you go over.
- **Pagination** for long lists. Today every expense is listed on one page.

**Data**

- **A fixed category list** or category management. Categories are free text now, so `Food` and `food` are
  separate categories.
- **CSV import and export.**
- **Currency choice** and locale-aware formatting. Amounts are always shown in USD (`en-US`).
- **A real database.** A single JSON file has no protection against concurrent writes: two `POST`s at the
  same moment can lose one of them.
- **Validating stored data.** Records in the data file are trusted as-is when read.

**Accounts**

- **Users and authentication.** Everyone who can reach the server sees, and can add to, the same expenses.
