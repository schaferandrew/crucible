// @vitest-environment node
import { expect, test } from 'vitest';
import { GET } from './api/account/route';

test('the account API returns acct_1', async () => {
  const res = await GET(new Request('http://localhost/api/account?id=acct_1'));
  expect(res.status).toBe(200);
  expect(await res.json()).toEqual({ name: 'Alice', plan: 'Pro' });
});

test('the account API answers 404 for an unknown account', async () => {
  const res = await GET(new Request('http://localhost/api/account?id=nobody'));
  expect(res.status).toBe(404);
});
