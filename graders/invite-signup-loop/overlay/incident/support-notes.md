# Support escalation: invited contributors stuck

Collected by support. Severity: contributors can't start assigned work.

- **rosa** (invited by grace, accepted the invite on 10/20): "The page keeps flashing between 'Welcome to Conduit' and the editor and never settles. Sometimes the browser says the page isn't responding."
- **tomek** (invited by grace, accepted 10/21): same flashing. He tried clearing cookies and signing in again: same thing.
- **pending@example.com** (invited, never clicked the link, says the email went to spam): signed up from the homepage instead, got "email has already been taken", clicked "Already have an account? Sign in", but has no password, so can't sign in. Stuck.
- Regular sign-ups are fine: they see the welcome screen once and then can write.

Engineering note from the on-call: rosa and tomek's accounts look normal in the admin view. We'd rather not hand-edit accounts in production; whatever the fix is should work for accounts that are already in this state.
