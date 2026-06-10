# Podman

OneSearch can run under Podman using the same compose file as Docker. This is a community-friendly path for homelabs and Linux desktops, but it is still the normal single-container compose deployment, not Kubernetes or OpenShift support.

## Start with podman compose

Download and edit the same files used by the Docker install:

```bash
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/demigodmode/OneSearch/main/.env.example
cp .env.example .env
```

Then start it with Podman Compose:

```bash
podman compose up -d
```

Some systems use the older standalone command instead:

```bash
podman-compose up -d
```

Check the service with:

```bash
podman compose ps
podman compose logs -f onesearch
```

## Rootless Podman notes

Rootless Podman runs containers as your user through a user namespace. That is good for local security, but it can make mounted file permissions less obvious than Docker.

If OneSearch cannot read a mounted source path:

- confirm the host directory is readable by your user
- confirm you are entering the container path in the UI, not the host path
- use the source form's **Test** button before saving
- check whether your Podman setup maps the mounted path with the IDs you expect

For many rootless setups, leaving `PUID` and `PGID` at the defaults is fine. If you use a shared service group for NAS or media folders, set them in `.env` the same way you would for Docker.

## SELinux labels

On SELinux systems such as Fedora, RHEL, CentOS Stream, and many NAS-style Linux installs, bind mounts may need a label suffix.

Use `:Z` for a private mount used by only this OneSearch container:

```yaml
volumes:
  - /mnt/nas/documents:/data/documents:ro,Z
```

Use `:z` when the same host path is shared with other containers:

```yaml
volumes:
  - /mnt/nas/media:/data/media:ro,z
```

If the source Test button reports that a path exists but is not readable, SELinux labels are one of the first things to check.

## Host path vs container path

The left side of a bind mount is the host path. The right side is the container path:

```yaml
volumes:
  - /home/alex/Documents:/data/documents:ro,Z
```

Add `/data/documents` as the source Root Path in OneSearch. Do not add `/home/alex/Documents`, because the app runs inside the container and cannot see that path directly.
