# Authentication

OneSearch uses JWT-based authentication for users. User-facing API requests require a valid user token except for setup, login, and health checks. Scripts can also use an API token, which only works for search. See [API tokens](#api-tokens). The remote-agent enrollment endpoint uses a single-use enrollment code instead, and the rest of the agent protocol uses a separate agent token.

## Setup wizard

The first time you open OneSearch, you'll see a setup wizard asking you to create the first account. Pick a username (3 to 50 characters) and a password (at least 8 characters), confirm the password, and you're the admin. You're logged in straight away.

Setup only works when there are no users at all. After the first account exists, the setup endpoint is disabled. If you lose access, see [Recovering access](#recovering-access).

## Logging in

### Web UI

Just go to http://localhost:8000 and you'll be redirected to the login page if you're not already authenticated. Enter your credentials and you're in. The token is stored in your browser. It isn't refreshed, so you log in again when it expires.

### API

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'
```

You'll get back an access token:

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer"
}
```

Use it in subsequent requests:

```bash
curl http://localhost:8000/api/sources \
  -H "Authorization: Bearer eyJhbGciOi..."
```

## Users and roles

Each person who signs in has their own account, and each account is either an admin or a member. Admins run the instance: they manage sources, agents, settings, users and the audit log, and they can search too. Members can search and open, preview and download documents. They also get their Account page and the theme setting.

Members don't see Sources, Status, Agents, Settings, Users, or Audit log in the navigation. If a member opens one of those pages by URL, they're sent back to search. The API returns 403 for those routes.

Everyone searches the same documents. Per-source access isn't available yet.

You can have as many admins as you need. The last active admin can't be demoted, disabled, or deleted. You also can't disable, demote, or delete your own account. These rules are enforced by the API, so scripts get the same answer as the web UI.

## Adding users

Go to **Admin > Users** and select **Create user**. Enter a username, pick a role, and set a temporary password. Give the username and the temporary password to the person through a channel you trust.

The new user has to choose their own password the first time they sign in. Until they do, they can't search or do anything else except change the password or sign out.

## Managing users

Each row on the Users page has an actions menu:

- **Make admin** or **Make member** changes the role.
- **Disable** or **Enable** turns the account off or back on. A disabled user can't sign in, and their API tokens stop working. Disabling is the normal way to remove someone. It can be undone, and their name stays on old audit entries.
- **Reset password** gives the user a new temporary password. They have to change it at their next sign-in.
- **Tokens** lists the user's API tokens. You can revoke any of them, but you can't create tokens for someone else.
- **Delete** removes the account. Use it for mistakes. For people who have left, disable the account instead.

Changing a role, disabling a user, or resetting a password ends that user's sessions and download links right away. Their next request is refused, and they have to sign in again.

## Sessions

Signing in creates a session that lasts for `SESSION_EXPIRE_HOURS`, 24 hours by default. A session also ends early when the account's role, status, or password changes, as described above.

When you change your own password, the browser you changed it from stays signed in. Your other sessions end, and so do download links you made earlier.

Sessions that were created before you upgraded to 1.8.0 keep working until they expire.

## Changing your password

Go to **Account** and use **Change password**. You need your current password to change it.

## API tokens

Scripts and other apps can use an API token instead of a password. Tokens are made on the **Account** page, under **API tokens**.

- Give the token a name and choose when it expires: never (the default), 30 days, 90 days, or 1 year.
- The token is shown once. Copy it before you close the dialog. OneSearch only stores a hash, so it can't show the token again.
- Tokens start with `os_`, so you can tell them apart from other secrets.
- A token can search, open, preview, and download documents. It can't do anything else. It can't change settings, manage sources, or create more tokens.
- You can revoke a token at any time from the Account page. Revoked and expired tokens get a 401.
- A token acts as the user who made it. If that user is disabled or deleted, the token stops working. A password change doesn't revoke tokens.

Send the token as a bearer token:

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Authorization: Bearer os_your_token" \
  -H "Content-Type: application/json" \
  -d '{"q": "kubernetes"}'
```

The CLI accepts tokens too. See [Using an API token](../cli/commands.md#using-an-api-token).

## Audit log

Admins can see the audit log under **Admin > Audit log**. The newest entries come first. You can filter by user or by kind of event, and page through older entries.

The log records:

- sign-ins and failed sign-ins
- users created, role changes, disabling, enabling, deleting, and password resets
- password changes made by a user
- API tokens created and revoked
- source added, changed, removed, and reindex requests
- agent enrollment codes created, agents approved, disabled, revoked, and changed
- settings changes, with the names of the settings that changed. The log never stores the values.

Searches and individual uses of API tokens aren't logged.

Entries are kept for 90 days by default. To change that, go to **Settings > Audit log** and set **Keep audit log for (days)**. Old entries are deleted once a day and when the server starts. Lowering the number removes older entries at the next cleanup.

Two things to know if other people use your instance:

- A failed sign-in stores the username that was typed, cut to 50 characters, and the client's IP address. If someone types their password into the username box by mistake, that password ends up in the log until it ages out.
- The IP address comes from the `X-Forwarded-For` and `X-Real-IP` headers. If you run a reverse proxy, set it up to overwrite those headers with the address it sees. Otherwise a client can send any address it likes, and the log will show that address.

## Recovering access

If you forget the password for the only admin, or every admin is locked out, reset a user's password from inside the container:

```bash
docker exec onesearch-app onesearch-admin reset-password alice
```

Use the container name from your compose file. The command works for any user, admin or member. It prints a temporary password:

```
Temporary password for alice: Xk3dP9mQw2Lr7TcV
alice must change it at the next sign-in. Their old sessions have ended.
```

The user has to choose a new password at their next sign-in, and their old sessions stop working. The command is written to the audit log as a password reset done from the command line.

If the username doesn't exist, the command says so and lists the usernames that do exist.

You can run the command as root. It switches to the app user before it touches the database, so it doesn't leave root-owned files behind.

## Configuration

Three environment variables control auth behavior:

**SESSION_SECRET**: The key used to sign JWT tokens. If you don't set this, a hardcoded fallback is used and you'll see a warning in the logs. Fine for development, but set a proper secret for anything else.

```bash
# Generate a good secret
openssl rand -base64 32
```

Changing this value ends every session. API tokens keep working, because they don't depend on it.

**SESSION_EXPIRE_HOURS**: How long sessions last before you need to log in again. Default is 24 hours.

**AUTH_RATE_LIMIT**: Max login attempts per minute from one IP address. Default is 5. Successful logins count too, and so do setup requests. After that, requests get rejected with a 429 status until the window resets.

## Rate limiting

The login endpoint is rate-limited to prevent brute force attacks. If someone (or something) hammers the login endpoint with bad credentials, they'll get locked out temporarily.

This is a simple in-memory rate limiter. It resets when the server restarts. Good enough for a homelab, but if you're exposing OneSearch to the internet you should put it behind a reverse proxy with its own rate limiting too.

## Security notes

- Passwords are hashed with bcrypt (not stored in plain text)
- API tokens are stored as hashes, the same way agent tokens are
- Tokens are signed with HS256 (HMAC-SHA256)
- The `/api/auth/setup` endpoint only works when no users exist
- The remote-agent protocol uses agent credentials and cannot be called with a user JWT

## Remote-agent credentials

Remote agents enroll with a 15-minute, single-use code. The server returns a separate agent token during enrollment, and the agent saves it before it enters the pending approval state. The token is not a user JWT and cannot log in to the web UI. Store it in the native credential store or the protected Docker state volume.

Disabling an agent temporarily blocks its token. Revoking an agent permanently invalidates the token and requires a new enrollment code. Do not copy an agent token into a user client or put it in a URL, compose file, or shell history.

OneSearch does not provide built-in OAuth login. A reverse proxy can use OAuth or SSO as an additional access layer, but OneSearch still uses its own user authentication behind that proxy.
