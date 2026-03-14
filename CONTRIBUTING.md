# Contributing

## Git workflow

- **Clone:** `git clone <repo-url> && cd Bandwidth-Test-Manager`
- **Branch (optional):** `git checkout -b feature/your-feature`
- **Commit:** `git add . && git commit -m "Description of change"`
- **Push:** `git push origin master` (or your branch; then open a Pull Request)

## Creating a release

1. Tag the commit: `git tag -a v1.0.0 -m "Release v1.0.0"`
2. Push the tag: `git push origin v1.0.0`
3. On GitHub: **Releases** → **Draft a new release** → choose the tag, add release notes, publish.

Or with GitHub CLI: `gh release create v1.0.0 --notes "Release v1.0.0"`

## Deployment

Deploy to a GCE instance using the bash script (Linux, macOS, or Windows via WSL/Git Bash):

```bash
./deploy-gce.sh INSTANCE_NAME [ZONE] [PROJECT]
```

See [README.md](README.md) for full deployment and install instructions.
