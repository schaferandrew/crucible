'use client';

import { useState } from 'react';

// Simulated database
const accounts = {
  acct_1: { name: 'Alice', plan: 'Pro' },
  acct_2: { name: 'Bob', plan: 'Basic' },
};

export default function AccountPage() {
  const [id] = useState<keyof typeof accounts>('acct_1');
  const account = accounts[id];

  return (
    <main>
      <h1>Account</h1>
      <p>Name: {account.name}</p>
      <p>Plan: {account.plan}</p>
    </main>
  );
}
