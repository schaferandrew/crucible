import { describe, it, expect } from 'vitest';
import request from 'supertest';
import app from './server.js';

// Gives testuser a known password through the reset flow, whatever the account was seeded with
async function resetPassword(username, newPassword) {
  const asked = await request(app).post('/api/reset-password-request').send({ username });
  const token = new URL(asked.body.resetUrl, 'http://localhost').searchParams.get('token');
  return request(app).post('/api/reset-password').send({ username, token, newPassword });
}

async function loginAs(username, password) {
  return request(app).post('/api/login').send({ username, password });
}

describe('Login Service', () => {
  it('should login with correct credentials', async () => {
    expect((await resetPassword('testuser', 'known-password')).status).toBe(200);
    const res = await loginAs('testuser', 'known-password');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.redirect).toBe('/dashboard.html');
  });

  it('should reject wrong password', async () => {
    await resetPassword('testuser', 'known-password');
    const res = await loginAs('testuser', 'wrongpassword');
    expect(res.status).toBe(401);
  });

  it('should reject unknown user', async () => {
    const res = await loginAs('nobody', 'whatever');
    expect(res.status).toBe(401);
  });

  it('should reject deactivated account', async () => {
    const res = await loginAs('deactivated', 'correctpassword');
    expect(res.status).toBe(403);
  });
});

describe('Dashboard', () => {
  it('should show the signed-in user their dashboard', async () => {
    await resetPassword('testuser', 'known-password');
    const agent = request.agent(app);
    await agent.post('/api/login').send({ username: 'testuser', password: 'known-password' });
    const res = await agent.get('/api/dashboard');
    expect(res.status).toBe(200);
    expect(res.body.user).toBe('testuser');
    expect(res.body.dashboardMessage).toBe('Welcome to your dashboard!');
  });
});

describe('Password reset', () => {
  it('should reject a reset with the wrong token', async () => {
    await request(app).post('/api/reset-password-request').send({ username: 'testuser' });
    const res = await request(app)
      .post('/api/reset-password')
      .send({ username: 'testuser', token: 'not-the-token', newPassword: 'x' });
    expect(res.status).toBe(400);
  });

  it('should not reset an unknown user', async () => {
    const res = await request(app).post('/api/reset-password-request').send({ username: 'nobody' });
    expect(res.status).toBe(404);
  });
});
