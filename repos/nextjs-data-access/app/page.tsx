import React from 'react';

// Simulated database
const accounts = {
  acct_1: { name: 'Alice', plan: 'Pro' },
  acct_2: { name: 'Bob', plan: 'Basic' },
};

export default function AccountPage() {
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
