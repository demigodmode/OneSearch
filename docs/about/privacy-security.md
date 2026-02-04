# Privacy & Security

OneSearch is designed with privacy and security as core principles.

## Privacy Guarantees

### No Outbound Connections

OneSearch never makes outbound network connections. All data stays on your local network.

No telemetry, no analytics, no update checks, no external API calls, no cloud services. Everything is self-contained.

### Your Data Stays Local

Everything lives on your infrastructure:

- Source files: Read-only access, never modified
- Search index: Stored locally in Meilisearch
- Metadata: Stored in local SQLite database
- Logs: Only on your system

### No Tracking

OneSearch doesn't track search queries, user behavior, usage statistics, or performance metrics. What happens on your server stays on your server.

---

## Security Features

### Network Isolation

In Docker deployment, Meilisearch runs on the internal Docker network only. It's not exposed to the host network. Only the OneSearch web UI is accessible (port 8000).

### Read-Only Source Mounts

Recommended docker-compose.yml configuration:

```yaml
volumes:
  - /host/documents:/data/documents:ro  # :ro = read-only
```

OneSearch can't modify your files, which prevents accidental corruption and reduces security risks.

### Non-Root Container

The OneSearch container runs as a non-root user (UID 1000) by default, limiting permissions and following security best practices.

### No Authentication (By Design)

OneSearch currently doesn't include authentication. It's designed for trusted networks like homelabs and private LANs, where you control network access via VPN, firewall, or reverse proxy.

Basic authentication is planned for Phase 2.

**Important**: Don't expose OneSearch directly to the internet without additional security measures.

---

## Security Considerations

### Network Security

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

### Data Sensitivity

OneSearch indexes full document content. Consider what files you're indexing, who has access to OneSearch, and what network security measures you have in place.

For sensitive documents, use VPN or reverse proxy auth, don't index highly sensitive files, or wait for per-source access controls (future feature).

### Container Security

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

### Meilisearch Master Key

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

## Security Updates

We take security seriously. Dependencies are updated regularly to address CVEs. Dependabot provides automated security alerts. Vulnerability scanning runs in CI/CD.

See the [Changelog](changelog.md) for security-related updates.

---

## Reporting Security Issues

Found a security vulnerability?

**Please don't open a public issue.**

Email the maintainers (see GitHub profile) with details. We'll respond within 48 hours and coordinate a fix and disclosure.

---

## Data Deletion

### Removing Indexed Data

```bash
# Stop OneSearch
docker-compose down

# Delete volumes (removes index and database)
docker-compose down -v
```

This deletes your search index and source configurations. Your original files are never touched.

### Removing a Source

Deleting a source via the UI, CLI, or API removes the source configuration, indexed file metadata, and documents from Meilisearch. Original files are never deleted.

---

## Compliance

### GDPR Considerations

OneSearch is self-hosted. You're the data controller.

- No data sent to third parties
- No processing outside your infrastructure
- You control data retention and deletion

If you index personal data, ensure you have appropriate legal basis, implement access controls, and document your data processing.

Consult a legal professional for specific compliance requirements.

### Data Residency

All data stays on your infrastructure. No cross-border data transfers, no cloud processing, full control over data location.

---

## Best Practices Summary

### For Privacy

Deploy on private networks only. Use VPN for remote access. Don't expose to public internet. Review what files you're indexing.

### For Security

Use strong Meilisearch master key. Mount sources read-only. Keep dependencies updated. Use reverse proxy with authentication if needed. Implement network-level access controls. Regular backups.

### For Production

Deploy behind VPN or reverse proxy. Monitor for security updates. Use separate sources for different security levels (future). Implement proper network segmentation. Regular security audits.

---

## Questions

Security concerns or questions?

- [Open a GitHub Issue](https://github.com/demigodmode/OneSearch/issues)
- [Start a Discussion](https://github.com/demigodmode/OneSearch/discussions)
- Email the maintainers (see GitHub profile)
