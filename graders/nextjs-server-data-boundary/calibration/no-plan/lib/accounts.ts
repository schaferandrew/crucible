// Simulated database
const accounts = {
  acct_1: { name: 'Alice', plan: 'Pro' },
  acct_2: { name: 'Bob', plan: 'Basic' },
};

export type Account = { name: string; plan: string };

export async function getAccount(id: string): Promise<Account | null> {
  return accounts[id as keyof typeof accounts] ?? null;
}
