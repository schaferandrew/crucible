import { getAccount } from '@/lib/accounts';

export default async function AccountPage() {
  const account = await getAccount('acct_1');

  if (!account) {
    return <p>Account not found</p>;
  }

  return (
    <main>
      <h1>Account</h1>
      <p>Name: {account.name}</p>
      <p>Plan: {account.plan}</p>
    </main>
  );
}
