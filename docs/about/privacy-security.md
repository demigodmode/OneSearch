# Privacy and security

OneSearch is self-hosted and does not include telemetry or analytics.

## Privacy guarantees

### Outbound connections

OneSearch server components do not contact external services by default. An optional remote agent connects outbound to the OneSearch server configured by its administrator. Source data travels only between that agent and the server.

Automatic installation is off by default, but every agent contacts the OneSearch GitHub release host for signed release metadata at startup and about every 24 hours. The request does not include indexed content, source paths, search queries, or the agent credential. Only native agents with `auto_update = true` download signed artifacts; Docker agents only report an available update and never replace their own image.

OneSearch does not send telemetry, analytics, search queries, or indexed content to a hosted OneSearch service.

### Where data is stored

Indexed data stays on infrastructure you control:

- Source files: Read-only access on the server or agent machine, never modified
- Search index and extracted content: Stored in the server's Meilisearch data
- Source, file, agent, and job metadata: Stored in the server database
- Agent configuration and credential: Stored on the agent machine
- Logs: Stored only on your systems

With on-agent processing, the agent sends extracted text and metadata to the server. With on-server processing, it sends changed originals to temporary server storage for extraction. The server does not retain those original-file transfers after processing. Searchable text and metadata remain in the central index in both modes.

### No tracking

OneSearch doesn't track search queries, user behavior, usage statistics, or performance metrics. What happens on your server stays on your server.

---

## Security features

### Network isolation

In Docker deployment, Meilisearch runs on the internal Docker network only. It's not exposed to the host network. Only the OneSearch web UI is accessible (port 8000).

### Read-only source mounts

Recommended docker-compose.yml configuration:

```yaml
volumes:
  - /host/documents:/data/documents:ro  # :ro = read-only
```

OneSearch can't modify your files, which prevents accidental corruption and reduces security risks.

### Non-root container

The OneSearch container runs as a non-root user (UID 1000) by default, limiting permissions and following security best practices.

### Built-in authentication

OneSearch includes JWT-based authentication with bcrypt password hashing. A setup wizard creates the initial admin account on first launch. Login is rate-limited to prevent brute force attacks.

For additional security layers (especially if exposing to the internet), consider pairing with a reverse proxy, VPN, or firewall rules.

See the [Authentication Guide](../administration/authentication.md) for details.

---

## Security considerations

### Network security

OneSearch is designed for trusted networks. Here are recommended deployment strategies:

**VPN Access Only**

```
Internet → VPN → Private Network → OneSearch
```

Users must connect via VPN to access OneSearch.

**Reverse Proxy with Auth**

```
Internet → Reverse Proxy (nginx/Caddy) → OneSearch
              ↓
          Authentication
```

Add authentication at the reverse proxy level using Basic Auth, OAuth (Authelia, Authentik), or SSO.

**Firewall Rules**

Restrict access to specific IP ranges:

```bash
# Allow only local network
iptables -A INPUT -p tcp --dport 8000 -s 192.168.1.0/24 -j ACCEPT
iptables -A INPUT -p tcp --dport 8000 -j DROP
```

### Data sensitivity

OneSearch indexes full document content. Consider what files you're indexing, who has access to OneSearch, and what network security measures you have in place.

For sensitive documents, use VPN or reverse proxy auth, don't index highly sensitive files, or wait for per-source access controls (future feature).

### Container security

Best practices:

```yaml
# docker-compose.yml
services:
  onesearch:
    # Read-only mounts
    volumes:
      - /host/docs:/data/docs:ro

    # Limit resources
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G

    # No privileged mode
    privileged: false

    # Drop capabilities
    cap_drop:
      - ALL
```

### Meilisearch master key

The `MEILI_MASTER_KEY` protects your Meilisearch instance.

Best practices:
- Generate a strong random key (32+ characters)
- Store it securely (in `.env` file, not committed to git)
- Use different keys for different deployments
- Don't use default or weak keys
- Don't share it publicly

Generate a secure key:

```bash
# Linux/macOS
openssl rand -base64 32

# Windows PowerShell
-join (1..32 | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
```

---

## Security updates

We take security seriously. Dependencies are updated regularly to address CVEs. Dependabot provides automated security alerts. Vulnerability scanning runs in CI/CD.

See the [Changelog](changelog.md) for security-related updates.

---

## Reporting security issues

Found a security vulnerability?

**Please don't open a public issue.**

Email the maintainers (see GitHub profile) with details. We'll respond within 48 hours and coordinate a fix and disclosure.

---

## Data deletion

### Removing indexed data

```bash
# Stop OneSearch
docker compose down

# Delete volumes (removes index and database)
docker compose down -v
```

This deletes your search index and source configurations. Your original files are never touched.

### Removing a source

Deleting a source via the UI, CLI, or API removes the source configuration, indexed file metadata, and documents from Meilisearch. Original files are never deleted.

---

## Compliance

### GDPR considerations

OneSearch is self-hosted. You're the data controller.

- No indexed content sent to third parties by OneSearch
- No processing outside your infrastructure
- You control data retention and deletion

If you index personal data, ensure you have appropriate legal basis, implement access controls, and document your data processing.

Consult a legal professional for specific compliance requirements.

### Data residency

You choose where the server, search index, database, source mounts, and agents run. OneSearch does not use cloud processing. If an update check is enabled, the agent makes an HTTPS request to the GitHub release host, so apply your own network and residency rules to that request.

---

## Best practices summary

### For privacy

Deploy on private networks only. Use VPN for remote access. Don't expose to public internet. Review what files you're indexing.

### For security

Use strong Meilisearch master key and SESSION_SECRET. Mount sources read-only. Keep dependencies updated. Use reverse proxy for additional security if needed. Implement network-level access controls. Regular backups.

### For production

Deploy behind VPN or reverse proxy. Monitor for security updates. Use separate sources for different security levels (future). Implement proper network segmentation. Regular security audits.

---

## Questions

Security concerns or questions?

- [Open a GitHub Issue](https://github.com/demigodmode/OneSearch/issues)
- [Start a Discussion](https://github.com/demigodmode/OneSearch/discussions)
- Email the maintainers (see GitHub profile)
