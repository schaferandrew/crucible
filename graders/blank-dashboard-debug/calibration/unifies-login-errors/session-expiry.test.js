import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import request from 'supertest';
import app from './server.js';

// Sessions last 30 seconds. The clock moves instead of the test waiting.
describe('Dashboard sessions', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('answers 401 for an expired session instead of 200 with blank data', async () => {
    const agent = request.agent(app);
    await agent.post('/api/login').send({ username: 'testuser', password: 'correctpassword' });
    expect((await agent.get('/api/dashboard')).status).toBe(200);
    vi.setSystemTime(Date.now() + 31 * 1000);
    const res = await agent.get('/api/dashboard');
    expect(res.status).toBe(401);
    expect(res.body.user).toBeUndefined();
  });

  it('answers 401 without a session', async () => {
    expect((await request(app).get('/api/dashboard')).status).toBe(401);
  });
});
