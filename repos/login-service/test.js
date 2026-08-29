const request = require('supertest');
const app = require('./server');

describe('Login Service', () => {
  it('should login with correct credentials', async () => {
    const res = await request(app)
      .post('/api/login')
      .send({ username: 'testuser', password: 'correctpassword' });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  it('should reject wrong password', async () => {
    const res = await request(app)
      .post('/api/login')
      .send({ username: 'testuser', password: 'wrongpassword' });
    expect(res.status).toBe(401);
  });

  it('should reject deactivated account', async () => {
    const res = await request(app)
      .post('/api/login')
      .send({ username: 'deactivated', password: 'correctpassword' });
    expect(res.status).toBe(403);
  });
});
