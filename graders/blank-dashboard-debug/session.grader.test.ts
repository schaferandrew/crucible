// Hidden tests for blank-dashboard-debug (formerly CODE-5); see crucible/graders.py.
// Time is the trigger: sessions last 30 seconds (accounts.json), and the tests move the clock instead
// of waiting, so "an expired session" is the same at every run.
import http from 'node:http';
import { createRequire } from 'node:module';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import request from 'supertest';
import { JSDOM, VirtualConsole, CookieJar } from 'jsdom';

const require = createRequire(import.meta.url);
const app = require('../../server.js');

const LOGIN = { username: 'testuser', password: 'correctpassword' };
const SECOND = 1000;
const DAY = 24 * 3600 * SECOND;

const later = (ms: number) => vi.setSystemTime(Date.now() + ms);
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2030-01-01T09:00:00Z'));
});
afterEach(() => {
  vi.useRealTimers();
});

async function signIn() {
  const agent = request.agent(app);
  const res = await agent.post('/api/login').send(LOGIN);
  expect(res.status).toBe(200);
  return agent;
}

describe('api: expired sessions get 401', () => {
  it('a session older than its 30 second lifetime gets 401, not 200 with blank data', async () => {
    const agent = await signIn();
    later(31 * SECOND);
    const res = await agent.get('/api/dashboard');
    expect(res.status).toBe(401);
  });

  it('a long-expired session stays rejected on every request', async () => {
    const agent = await signIn();
    later(DAY);
    expect((await agent.get('/api/dashboard')).status).toBe(401);
    expect((await agent.get('/api/dashboard')).status).toBe(401);
  });

  it('the cookie of a logged-out session gets 401', async () => {
    const login = await request(app).post('/api/login').send(LOGIN);
    const cookie = login.headers['set-cookie'][0].split(';')[0];
    expect((await request(app).get('/api/dashboard').set('Cookie', cookie)).status).toBe(200);
    await request(app).post('/api/logout').set('Cookie', cookie);
    const res = await request(app).get('/api/dashboard').set('Cookie', cookie);
    expect(res.status).toBe(401);
  });

  it('a request without a session gets 401', async () => {
    const res = await request(app).get('/api/dashboard');
    expect(res.status).toBe(401);
  });
});

// A browser page over the real app: jsdom runs the page's own scripts, fetch goes to the app with the jar's cookies
let server: http.Server;
let base: string;

beforeAll(async () => {
  server = http.createServer(app);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  base = `http://127.0.0.1:${(server.address() as any).port}`;
});
afterAll(async () => {
  await new Promise((resolve) => server.close(resolve));
});

async function browser() {
  const jar = new CookieJar();
  const res = await fetch(`${base}/api/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(LOGIN),
  });
  expect(res.status).toBe(200);
  for (const cookie of res.headers.getSetCookie()) jar.setCookieSync(cookie, base);
  return jar;
}

async function openDashboard(jar: CookieJar) {
  const navigations: string[] = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', (error: Error) => {
    if (/navigation/i.test(error.message)) navigations.push(error.message);
  });
  const dom = await JSDOM.fromURL(`${base}/dashboard.html`, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    cookieJar: jar,
    virtualConsole,
    beforeParse(window: any) {
      window.fetch = async (input: any, init: any = {}) => {
        const url = new URL(typeof input === 'string' ? input : input.url, window.location.href).href;
        const headers = new Headers(init.headers || {});
        const cookie = jar.getCookieStringSync(url);
        if (cookie) headers.set('cookie', cookie);
        const res = await fetch(url, { ...init, headers });
        for (const set of res.headers.getSetCookie()) jar.setCookieSync(set, url);
        return res;
      };
    },
  });
  const doc = dom.window.document;
  await sleep(500);
  for (let i = 0; i < 30 && !navigations.length && doc.getElementById('user')?.textContent === 'Loading...'; i++) {
    await sleep(50);
  }
  await sleep(100);
  const body = doc.body.cloneNode(true) as HTMLElement;
  body.querySelectorAll('script, style').forEach((node) => node.remove());
  const text = (body.textContent || '').replace(/\s+/g, ' ').trim();
  const shown = (id: string) => (doc.getElementById(id)?.textContent || '').trim();
  const view = {
    navigated: navigations.length > 0,
    user: shown('user'),
    message: shown('message'),
    // the visible page offers a way to log in (script text left out), or it already sent the visitor there
    prompt:
      navigations.length > 0 ||
      /log\s?in|sign\s?in/i.test(text) ||
      !!doc.querySelector('a[href*="login"], form#loginForm, input[type="password"]'),
  };
  dom.window.close();
  return view;
}

describe('ui: a login prompt instead of a blank dashboard', () => {
  it('an expired session is sent to log in', async () => {
    const jar = await browser();
    later(31 * SECOND);
    const view = await openDashboard(jar);
    expect(view.prompt).toBe(true);
  });

  it('a logged-out session is sent to log in', async () => {
    const jar = await browser();
    await fetch(`${base}/api/logout`, { method: 'POST', headers: { cookie: jar.getCookieStringSync(base) } });
    const view = await openDashboard(jar);
    expect(view.prompt).toBe(true);
  });

  it('a visitor without a session is sent to log in', async () => {
    const view = await openDashboard(new CookieJar());
    expect(view.prompt).toBe(true);
  });
});

describe('normal sessions: still work until they expire', () => {
  it('a fresh session gets its dashboard, and is rejected only once it has expired', async () => {
    const agent = await signIn();
    later(5 * SECOND);
    const fresh = await agent.get('/api/dashboard');
    expect(fresh.status).toBe(200);
    expect(fresh.body.user).toBe('testuser');
    expect(fresh.body.dashboardMessage).toBe('Welcome to your dashboard!');
    later(26 * SECOND);
    expect((await agent.get('/api/dashboard')).status).toBe(401);
  });

  it('logging in again after expiry gives a working session', async () => {
    const agent = await signIn();
    later(DAY);
    expect((await agent.get('/api/dashboard')).status).toBe(401);
    expect((await agent.post('/api/login').send(LOGIN)).status).toBe(200);
    const res = await agent.get('/api/dashboard');
    expect(res.status).toBe(200);
    expect(res.body.user).toBe('testuser');
  });

  it('each session expires on its own clock', async () => {
    const first = await signIn();
    later(20 * SECOND);
    const second = await signIn();
    later(15 * SECOND);
    expect((await first.get('/api/dashboard')).status).toBe(401);
    const res = await second.get('/api/dashboard');
    expect(res.status).toBe(200);
    expect(res.body.user).toBe('testuser');
  });

  it('logging out ends the session', async () => {
    const agent = await signIn();
    expect((await agent.get('/api/dashboard')).status).toBe(200);
    await agent.post('/api/logout');
    expect((await agent.get('/api/dashboard')).status).toBe(401);
  });

  it('the dashboard page shows the user while the session lasts, then a login prompt', async () => {
    const jar = await browser();
    const fresh = await openDashboard(jar);
    expect(fresh.user).toBe('testuser');
    expect(fresh.message).toBe('Welcome to your dashboard!');
    expect(fresh.navigated).toBe(false);
    later(31 * SECOND);
    const expired = await openDashboard(jar);
    expect(expired.prompt).toBe(true);
  });
});
