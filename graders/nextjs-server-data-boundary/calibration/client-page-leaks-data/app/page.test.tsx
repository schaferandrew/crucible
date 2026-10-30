import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';
import { GET } from './api/account/route';
import AccountPage from './page';

afterEach(cleanup);

test('the account page renders the name and plan for acct_1', async () => {
  render(<AccountPage />);
  expect(screen.getByText('Name: Alice')).toBeDefined();
  expect(screen.getByText('Plan: Pro')).toBeDefined();
  expect(screen.queryByText('Loading...')).toBeNull();
});

test('the account API returns acct_1', async () => {
  const res = await GET(new Request('http://localhost/api/account?id=acct_1'));
  expect(res.status).toBe(200);
  expect(await res.json()).toEqual({ name: 'Alice', plan: 'Pro' });
});

test('the account API answers 404 for an unknown account', async () => {
  const res = await GET(new Request('http://localhost/api/account?id=nobody'));
  expect(res.status).toBe(404);
});
