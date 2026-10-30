# Contributor invites (CONTRIB-88)

Editors invite contributors by email from the editor dashboard. The flow:

1. `POST /api/invites` creates the account immediately, with `accountState: "invited"` and no password, so the editor can assign it work before the person has even signed in.
2. The email links to `/invite/:token`. The contributor picks a username and password, accepts the contributor terms, and lands in the editor ready to write.
3. Invited contributors aren't asked for a bio: their editor already set them up, and asking again was the top complaint in the pilot.

`accountState` stays `"invited"` after the invite is accepted; editors use it to see which contributors came through invites.

Someone who signs up from the homepage with an address that has a pending invite gets that invited account, rather than an "email has already been taken" error, so they don't lose the work their editor assigned them.
