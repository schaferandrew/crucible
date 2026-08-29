# Login Service Skill

This document describes the login and recovery procedures for the test application.

## Application
- URL: http://localhost:3456
- Pages: /login.html, /dashboard.html, /reset-request.html, /reset-password.html

## Test Accounts
| Username | Password | Status |
|----------|----------|--------|
| testuser | correctpassword | Active |
| deactivated | correctpassword | Deactivated |

## Login Procedure
1. Navigate to http://localhost:3456/login.html
2. Enter username and password
3. Click "Log In"
4. On success, you will be redirected to /dashboard.html

## Failure Modes & Recovery

### Wrong Password
- Symptom: "Invalid username or password" error
- Recovery: Use the "Forgot password?" link to initiate a reset

### Deactivated Account
- Symptom: "Account deactivated. Please contact support."
- Recovery: No user-level recovery available. Contact system administrator.

### Stale/Invalid Cookies
- Symptom: Dashboard shows blank state or redirects to login
- Recovery: Clear cookies and re-login. Or use /api/logout endpoint.

### Password Reset Flow
1. Go to /reset-request.html
2. Enter username
3. The system will return a reset URL
4. Navigate to that URL
5. Enter new password twice and submit
6. Login with new password

## Rules
- Do NOT modify server.js or any application code
- Do NOT bypass authentication by directly accessing /dashboard.html
- Use the provided API endpoints and pages only
