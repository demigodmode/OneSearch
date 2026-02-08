# Roadmap

OneSearch is under active development. Here's what's planned for future releases.

**Current status**: Phase 1 is complete (v0.7.2). Phase 2 is next — UI redesign, theme system, and E2E testing.

---

## Phase 1 (Complete)

Released as v0.7.2.

- Office document support (Word, Excel, PowerPoint)
- Document preview page with syntax highlighting
- JWT authentication with setup wizard and rate limiting
- Scheduled indexing with APScheduler (per-source cron schedules)
- Security fixes (PyJWT migration, dependency updates)

---

## Phase 2 (Next)

UI overhaul and polish.

### UI Redesign

- New search page layout (#61)
- Admin dashboard redesign (#62)
- Source management improvements (#63)
- Status page overhaul (#64)
- Document preview redesign (#65)
- Mobile-responsive layout (#66)
- Theme system with light/dark modes (#38, #67)
- E2E test coverage (#20)

### Search Enhancements

- Saved searches
- Search history
- Advanced filters (date range, file size, metadata)
- Export results (CSV/JSON)

### Additional File Types

- Image metadata (EXIF)
- Archive files (.zip, .tar.gz)
- Email (.eml, .mbox)
- Better code file support

---

## Phase 3

Target: v0.8.0

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

### Performance

- Distributed indexing for large libraries
- Incremental backups
- Redis caching

---

## Phase 4 & Beyond

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

### Phase 1 (Current)

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
