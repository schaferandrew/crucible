const express = require('express');
const cookieParser = require('cookie-parser');
const bodyParser = require('body-parser');
const path = require('path');

const app = express();
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());
app.use(cookieParser('benchmark-secret'));
app.use(express.static(path.join(__dirname, 'public')));

// Simulated user database
const users = {
  testuser: {
    password: 'correctpassword',
    active: true,
    resetToken: null,
  },
  deactivated: {
    password: 'correctpassword',
    active: false,
    resetToken: null,
  },
};

// Session state for stale cookie simulation
const sessions = new Map();

// C5: intermittent blank dashboard - triggered when session is expired
function getDashboardData(req) {
  const sessionId = req.cookies.sessionId;
  if (!sessionId) {
    return { error: 'no_session' };
  }
  const session = sessions.get(sessionId);
  if (!session) {
    return { error: 'stale_session' };
  }
  if (session.expiresAt < Date.now()) {
    return { error: 'expired_session' };
  }
  return {
    user: session.user,
    dashboardMessage: 'Welcome to your dashboard!',
  };
}

// Routes
app.get('/', (req, res) => {
  res.redirect('/login.html');
});

app.post('/api/login', (req, res) => {
  const { username, password } = req.body;

  if (!users[username]) {
    return res.status(401).json({ error: 'invalid_credentials' });
  }

  const user = users[username];

  if (!user.active) {
    return res.status(403).json({ error: 'account_deactivated' });
  }

  if (user.password !== password) {
    return res.status(401).json({ error: 'invalid_credentials' });
  }

  // Create session
  const sessionId = 'sess_' + Math.random().toString(36).slice(2);
  sessions.set(sessionId, {
    user: username,
    expiresAt: Date.now() + 1000 * 60 * 30, // 30 minutes
  });

  res.cookie('sessionId', sessionId, { signed: true, httpOnly: true });
  return res.json({ success: true, redirect: '/dashboard.html' });
});

app.post('/api/logout', (req, res) => {
  const sessionId = req.cookies.sessionId;
  if (sessionId) {
    sessions.delete(sessionId);
  }
  res.clearCookie('sessionId');
  res.json({ success: true });
});

app.post('/api/reset-password-request', (req, res) => {
  const { username } = req.body;
  if (!users[username]) {
    return res.status(404).json({ error: 'user_not_found' });
  }
  const token = 'reset_' + Math.random().toString(36).slice(2);
  users[username].resetToken = token;
  return res.json({ success: true, resetUrl: `/reset-password.html?token=${token}&user=${username}` });
});

app.post('/api/reset-password', (req, res) => {
  const { username, token, newPassword } = req.body;
  const user = users[username];
  if (!user || user.resetToken !== token) {
    return res.status(400).json({ error: 'invalid_token' });
  }
  user.password = newPassword;
  user.resetToken = null;
  return res.json({ success: true });
});

app.get('/api/dashboard', (req, res) => {
  const data = getDashboardData(req);
  if (data.error) {
    // C5 BUG: Returns 200 with blank data instead of proper error
    // This causes the UI to show a blank state intermittently
    return res.status(200).json({ user: null, dashboardMessage: '' });
  }
  return res.json(data);
});

// Admin endpoint to expire a session (for testing)
app.post('/api/admin/expire-session', (req, res) => {
  const { sessionId } = req.body;
  const session = sessions.get(sessionId);
  if (session) {
    session.expiresAt = 0;
  }
  return res.json({ success: true });
});

const PORT = process.env.PORT || 3456;
app.listen(PORT, () => {
  console.log(`Login service running on http://localhost:${PORT}`);
});

module.exports = app;
