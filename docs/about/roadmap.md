# Roadmap

OneSearch is under active development. Here's what's planned for future releases.

**Current status**: Milestone 2 nearly complete (v0.9.0--v0.11.0) -- UI redesign done, theme system shipped. Light/dark toggle (#113) is the remaining item before closing out MS-2.

---

## Milestone 1 (Complete)

Released across v0.5.0--v0.7.0.

- Unified Docker image with CI/CD (v0.5.0)
- Office document support -- Word, Excel, PowerPoint (v0.6.0)
- Document preview page with syntax highlighting (v0.6.0)
- JWT authentication with setup wizard and rate limiting (v0.7.0)
- Scheduled indexing with APScheduler, per-source cron schedules (v0.7.0)
- Security hardening pass -- auth enforcement, CORS, path restriction (v0.7.2)
- Code and config file type classification (v0.8.0)

---

## Milestone 2 (In Progress)

UI overhaul and polish. Started in v0.9.0.

### UI Redesign (Done)

- Search page layout -- hero removed, search box is first element (v0.9.0)
- Admin dashboard redesign (v0.9.0)
- Source management improvements with container queries (v0.9.0)
- Status page overhaul -- compact inline status bar (v0.9.0)
- Document preview -- lazy-loaded with PrismLight (v0.9.0)
- Accessibility pass -- focus rings, touch targets, reduced motion (v0.9.0)
- Amber accent palette (v0.9.1)

### Still Open

- Light/dark toggle (#113)

### Search Enhancements

- Saved searches
- Search history
- Advanced filters (date range, file size, metadata)
- Export results (CSV/JSON)

### Additional File Types

- Image metadata (EXIF)
- Archive files (.zip, .tar.gz)
- Email (.eml, .mbox)

---

## Milestone 3

### Cloud Storage

- Cloud storage connectors via rclone
  - Google Drive
  - Dropbox
  - OneDrive
  - S3-compatible storage

### Advanced Features

- Semantic search using embeddings
- Obsidian vault support (backlinks, tags)
- Custom extractor plugins
- Faceted search

### Testing

- E2E and integration test coverage (#20)

### Performance

- Distributed indexing for large libraries
- Incremental backups
- Redis caching

---

## Milestone 4 & Beyond

Target: v1.0.0

### Enterprise Features

- SSO integration (LDAP, SAML, OAuth)
- Teams and organizations (multi-tenant)
- Advanced analytics
- API rate limiting

### Ecosystem

- Mobile apps (iOS/Android)
- Desktop clients (Electron)
- Browser extensions
- Webhooks and integrations

### AI & ML

- Document summarization
- Smart auto-tagging
- OCR support for images in PDFs
- Natural language queries ("PDFs from last month about Docker")

---

## Feature Requests

Have an idea? We'd love to hear it.

Check [existing issues](https://github.com/demigodmode/OneSearch/issues) first, then open a new issue with the `enhancement` label. Describe your use case and why it's valuable.

[Request a Feature](https://github.com/demigodmode/OneSearch/issues/new)

---

## Contributing

Want to help build these features?

- Check [open issues](https://github.com/demigodmode/OneSearch/issues)
- Read the [Contributing Guide](../development/contributing.md)
- Join [GitHub Discussions](https://github.com/demigodmode/OneSearch/discussions)

[View Open Issues](https://github.com/demigodmode/OneSearch/issues)

---

## Release Schedule

We follow a continuous delivery model:

- Minor releases (v0.6.0, v0.7.0) every 1-2 months with new features
- Patch releases (v0.6.1, v0.6.2) as needed for bugs and security
- Major releases (v1.0.0) for significant milestones

All releases follow [Semantic Versioning](https://semver.org/).

---

## Stability & Backwards Compatibility

### Milestone 2 (Current)

Core features are stable and production-ready. The API may change in minor releases (v0.x.0). Database migrations are handled automatically.

### v1.0.0 (Stable Release)

Once we reach v1.0.0:
- Stable, production-ready for all features
- Backwards compatibility guaranteed
- API stability with proper versioning
- Long-term support

---

## Community Input

The roadmap isn't set in stone. We prioritize based on:

1. User feedback - what's most requested?
2. Use cases - what problems need solving?
3. Complexity - what can ship quickly vs. long-term projects?
4. Community contributions - what are people building?

Your input matters. Share your thoughts in [GitHub Discussions](https://github.com/demigodmode/OneSearch/discussions).

---

## Stay Updated

Follow development progress:

- **GitHub**: Watch the repository
- **Releases**: Subscribe to [release notifications](https://github.com/demigodmode/OneSearch/releases)
- **Changelog**: Check the [Changelog](changelog.md)

---

## Questions

- [GitHub Issues](https://github.com/demigodmode/OneSearch/issues) - bugs, feature requests
- [GitHub Discussions](https://github.com/demigodmode/OneSearch/discussions) - questions, ideas
