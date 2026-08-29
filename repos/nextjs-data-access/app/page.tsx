import React from 'react';

// Simulated database
const accounts = {
  acct_1: { name: 'Alice', plan: 'Pro' },
  acct_2: { name: 'Bob', plan: 'Basic' },
};

export default function AccountPage() {
  // BUG: Using useState in a Server Component is wrong in Next.js App Router
  // The correct fix is either to fetch data directly (it's already server-side)
  // or to convert this to a Client Component with 'use client'
  const [account, setAccount] = React.useState(null);

  React.useEffect(() => {
    fetch('/api/account?id=acct_1')
      .then(r => r.json())
      .then(data => setAccount(data));
  }, []);

  if (!account) {
    return <p>Loading...</p>;
  }

  return (
    <main>
      <h1>Account</h1>
      <p>Name: {account.name}</p>
      <p>Plan: {account.plan}</p>
    </main>
  );
}
