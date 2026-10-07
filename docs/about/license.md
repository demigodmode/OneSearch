# License

OneSearch is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0-only)**.

[View Full License on GitHub](https://github.com/demigodmode/OneSearch/blob/main/LICENSE)

---

## What This Means

### You Can

**Use** OneSearch freely for personal or commercial purposes.

**Modify** the source code to fit your needs.

**Distribute** OneSearch to others.

**Deploy** OneSearch on your own servers.

### You Must

**Provide source code** if you modify and deploy OneSearch on a network server.

**Keep the same license** (AGPL-3.0) for derivative works.

**Include copyright notices** and license text.

**State changes** you made to the code.

### You Cannot

**Sublicense** or change the license terms.

**Hold liable** the authors or copyright holders.

**Use trademarks** without permission (project name, logo, etc.).

---

## AGPL vs GPL

The AGPL is similar to the GPL, with one important difference:

**GPL**: Only requires source code disclosure if you distribute the software.

**AGPL**: Requires source code disclosure if you deploy the software as a network service.

This ensures OneSearch remains open source even when used as a hosted service.

---

## Why AGPL

We chose AGPL-3.0 to ensure:

**OneSearch stays open source** - Even if someone deploys a modified version as a service, they must share their changes.

**Community benefits** - Improvements made by anyone benefit everyone.

**Freedom preserved** - Users can always access, modify, and run the code.

---

## Dependencies

OneSearch's dependencies use licenses compatible with AGPL-3.0. Most are permissive, a few are not:

- Python packages: mostly MIT, BSD and Apache-2.0. `chardet` is LGPL.
- JavaScript packages: MIT, BSD, Apache-2.0
- Bundled fonts (Outfit, JetBrains Mono): SIL Open Font License 1.1
- Meilisearch: MIT License

The Docker image also ships two command-line tools that OneSearch runs but doesn't link against:

- `ffprobe`, from FFmpeg, under LGPL v2.1 or later. It's built from the official FFmpeg source release named in the `Dockerfile`, with the build flags shown there. The license text is in the image at `/usr/share/licenses/ffmpeg`.
- ExifTool, from Debian's package, under the Artistic License or GPL.

See the `NOTICE` file in the repository for the full list.

---

## Commercial Use

Yes, you can use OneSearch commercially. The AGPL doesn't restrict commercial use.

However, if you modify OneSearch and deploy it as a service (e.g., offering search-as-a-service to customers), you must:

1. Provide the source code to your users
2. License your modifications under AGPL-3.0
3. Include installation instructions

---

## Attribution

When using OneSearch:

- Keep the license file (LICENSE) in your repository
- Credit the original authors
- Link back to https://github.com/demigodmode/OneSearch

---

## Questions

If you have questions about licensing:

- [Open a GitHub Discussion](https://github.com/demigodmode/OneSearch/discussions)
- [Read the full AGPL-3.0 text](https://www.gnu.org/licenses/agpl-3.0.en.html)
- Consult with a legal professional for specific use cases

---

[View LICENSE File](https://github.com/demigodmode/OneSearch/blob/main/LICENSE)
