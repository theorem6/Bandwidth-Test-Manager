Bandwidth Test Manager — offline / private bundle
===================================================

This archive is produced by pack-release.sh from the engineering repo. It contains
scripts/, etc/, web/ (built static UI), and install.sh.

Install (Debian/Ubuntu, as root):

  tar xzf bandwidth-test-manager-*.tar.gz
  cd into the directory that contains install.sh (same level as scripts/ and web/)
  sudo ./install.sh

CLI only (no web UI):

  sudo ./install.sh --no-web

Private GitLab: use private-download-install.sh with GITLAB_TOKEN, or host this
tarball on HTTPS and set BWM_TARBALL_URL when running that script.

Online install from the repo (separate from this bundle): install.sh can fetch
either a source archive (default) or git-clone the project; see README
"Source: archive vs git" (BWM_SOURCE, BWM_REPO, BWM_REF).
