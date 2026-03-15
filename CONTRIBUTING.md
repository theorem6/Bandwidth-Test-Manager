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

Deploy to a GCE instance using the bash script (Linux, macOS):

```bash
./deploy-gce.sh INSTANCE_NAME [ZONE] [PROJECT]
```

**Deploy from Windows**

- **Option A:** Use [WSL](https://docs.microsoft.com/en-us/windows/wsl/install) or [Git for Windows](https://git-scm.com/download/win), then run: `bash deploy-gce.sh INSTANCE_NAME [ZONE] [PROJECT]`.
- **Option B:** From the server (SSH in, then): clone the repo, build the frontend (`cd web/frontend && npm install && npm run build`), then from the repo root run `sudo ./install.sh`.

After deployment, use **Setup** for backend status, configurable **Users** (auth), **Recent SLA alerts**, timezone/NTP, and data purge. See [README.md](README.md) and [docs/ISP-ROADMAP.md](docs/ISP-ROADMAP.md) for ISP features (SLAs, webhooks, retention, summary reports).
