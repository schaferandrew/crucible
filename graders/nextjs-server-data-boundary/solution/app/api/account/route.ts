import { NextResponse } from 'next/server';
import { getAccount } from '@/lib/accounts';

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const account = await getAccount(searchParams.get('id') ?? '');
  if (!account) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }
  return NextResponse.json(account);
}
