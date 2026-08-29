import { NextResponse } from 'next/server';

const accounts = {
  acct_1: { name: 'Alice', plan: 'Pro' },
  acct_2: { name: 'Bob', plan: 'Basic' },
};

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get('id');
  if (!id || !accounts[id as keyof typeof accounts]) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }
  return NextResponse.json(accounts[id as keyof typeof accounts]);
}
