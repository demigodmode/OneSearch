# Authentication

OneSearch uses JWT-based authentication. Every request to the API (except the setup and login endpoints) requires a valid token.

## Setup Wizard

The first time you open OneSearch, you'll see a setup wizard asking you to create an admin account. Pick a username and password, and that's it — you're the admin.

This only works once. After the initial account is created, the setup endpoint is disabled. If you need to reset your credentials, you'll need to clear the `users` table in the database.

## Logging In

### Web UI

Just go to http://localhost:8000 and you'll be redirected to the login page if you're not already authenticated. Enter your credentials and you're in. The token is stored in your browser and refreshed automatically.

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

## Configuration

Three environment variables control auth behavior:

**SESSION_SECRET** — The key used to sign JWT tokens. If you don't set this, a hardcoded fallback is used and you'll see a warning in the logs. Fine for development, but set a proper secret for anything else.

```bash
# Generate a good secret
openssl rand -base64 32
```

**SESSION_EXPIRE_HOURS** — How long tokens last before you need to log in again. Default is 24 hours.

**AUTH_RATE_LIMIT** — Max failed login attempts per minute. Default is 5. After that, login requests get rejected with a 429 status until the window resets.

## Rate Limiting

The login endpoint is rate-limited to prevent brute force attacks. If someone (or something) hammers the login endpoint with bad credentials, they'll get locked out temporarily.

This is a simple in-memory rate limiter — it resets when the server restarts. Good enough for a homelab, but if you're exposing OneSearch to the internet you should put it behind a reverse proxy with its own rate limiting too.

## Security Notes

- Passwords are hashed with bcrypt (not stored in plain text)
- Tokens are signed with HS256 (HMAC-SHA256)
- The `/api/auth/setup` endpoint only works when no users exist
- All API endpoints except `/api/auth/setup`, `/api/auth/login`, and `/api/health` require authentication
