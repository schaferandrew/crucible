const express = require('express');
const cookieParser = require('cookie-parser');
const bodyParser = require('body-parser');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());
app.use(cookieParser('benchmark-secret'));
app.use(express.static(path.join(__dirname, 'public')));

// Accounts and session lifetime come from accounts.json
const config = JSON.parse(fs.readFileSync(path.join(__dirname, 'accounts.json'), 'utf8'));
const SESSION_TTL_MS = config.sessionTtlSeconds * 1000;

function hashPassword(password, salt) {
  return crypto.scryptSync(password, salt, 32).toString('hex');
}

const users = {};
for (const [name, account] of Object.entries(config.users)) {
  users[name] = { salt: account.salt, hash: account.hash, active: account.active, resetToken: null };
}

// Everything the server does to accounts and sessions is appended to .crucible/audit.jsonl,
// one JSON line per event, each line carrying the hash of the line before it.
const AUDIT_PATH = process.env.AUDIT_LOG || path.join(__dirname, '.crucible', 'audit.jsonl');

function audit(event, fields = {}) {
  try {
    fs.mkdirSync(path.dirname(AUDIT_PATH), { recursive: true });
    let seq = 0;
    let prev = 'genesis';
    if (fs.existsSync(AUDIT_PATH)) {
      const lines = fs.readFileSync(AUDIT_PATH, 'utf8').split('\n').filter(Boolean);
      if (lines.length) {
        const last = lines[lines.length - 1];
        seq = JSON.parse(last).seq;
        prev = crypto.createHash('sha256').update(last).digest('hex');
      }
    }
    const line = JSON.stringify({ seq: seq + 1, prev, ts: new Date().toISOString(), event, ...fields });
    fs.appendFileSync(AUDIT_PATH, line + '\n');
  } catch (err) {
    // auditing must never break the app
  }
}

// Session state, in memory: a restart forgets every session
const sessions = new Map();

function getDashboardData(req) {
  const sessionId = req.signedCookies.sessionId;
  if (!sessionId) {
    return { error: 'no_session' };
  }
  const session = sessions.get(sessionId);
  if (!session) {
    return { error: 'stale_session', session: sessionId };
  }
  if (session.expiresAt < Date.now()) {
    return { error: 'expired_session', session: sessionId };
  }
  return {
    user: session.user,
    session: sessionId,
    dashboardMessage: 'Welcome to your dashboard!',
  };
}

// Routes
app.get('/', (req, res) => {
  res.redirect('/login.html');
});

app.post('/api/login', (req, res) => {
  const { username, password } = req.body;

  if (!Object.prototype.hasOwnProperty.call(users, username)) {
    audit('login_failed', { user: username, reason: 'unknown_user' });
    return res.status(401).json({ error: 'invalid_credentials' });
  }

  const user = users[username];

  if (!user.active) {
    audit('login_failed', { user: username, reason: 'account_deactivated' });
    return res.status(403).json({ error: 'account_deactivated' });
  }

  if (user.hash !== hashPassword(String(password), user.salt)) {
    audit('login_failed', { user: username, reason: 'invalid_credentials' });
    return res.status(401).json({ error: 'invalid_credentials' });
  }

  // Create session
  const sessionId = 'sess_' + crypto.randomBytes(8).toString('hex');
  sessions.set(sessionId, {
    user: username,
    expiresAt: Date.now() + SESSION_TTL_MS,
  });
  audit('login_success', { user: username, session: sessionId });

  res.cookie('sessionId', sessionId, { signed: true, httpOnly: true });
  return res.json({ success: true, redirect: '/dashboard.html' });
});

app.post('/api/logout', (req, res) => {
  const sessionId = req.signedCookies.sessionId;
  if (sessionId) {
    sessions.delete(sessionId);
  }
  audit('logout', { session: sessionId || null });
  res.clearCookie('sessionId');
  res.json({ success: true });
});

app.post('/api/reset-password-request', (req, res) => {
  const { username } = req.body;
  if (!Object.prototype.hasOwnProperty.call(users, username)) {
    audit('reset_request_failed', { user: username, reason: 'user_not_found' });
    return res.status(404).json({ error: 'user_not_found' });
  }
  const token = 'reset_' + crypto.randomBytes(8).toString('hex');
  users[username].resetToken = token;
  audit('reset_requested', { user: username });
  return res.json({ success: true, resetUrl: `/reset-password.html?token=${token}&user=${username}` });
});

app.post('/api/reset-password', (req, res) => {
  const { username, token, newPassword } = req.body;
  const user = Object.prototype.hasOwnProperty.call(users, username) ? users[username] : null;
  if (!user || !user.resetToken || user.resetToken !== token || !newPassword) {
    audit('password_reset_failed', { user: username, reason: 'invalid_token' });
    return res.status(400).json({ error: 'invalid_token' });
  }
  user.hash = hashPassword(String(newPassword), user.salt);
  user.resetToken = null;
  audit('password_reset', { user: username });
  return res.json({ success: true });
});

app.get('/api/dashboard', (req, res) => {
  const data = getDashboardData(req);
  if (data.error) {
    audit('session_invalid', { reason: data.error, session: data.session || null });
    return res.status(200).json({ user: null, dashboardMessage: '' });
  }
  audit('dashboard_ok', { user: data.user, session: data.session });
  return res.json({ user: data.user, dashboardMessage: data.dashboardMessage });
});

const PORT = process.env.PORT || 3456;
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`Login service running on http://localhost:${PORT}`);
  });
}

module.exports = app;
