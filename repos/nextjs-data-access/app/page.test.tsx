import { expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';
import AccountPage from './page';

test('renders account name and plan', async () => {
  render(<AccountPage />);
  expect(await screen.findByText('Alice')).toBeDefined();
  expect(await screen.findByText('Pro')).toBeDefined();
});
