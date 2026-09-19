#!/bin/bash
# fgoa-wine — build the release archive and publish it.
#
# A release here is one file: the archive of this folder. It unpacks into a game folder as
# <game>/fgoa-wine, which is where install.sh expects to find itself. The contents come from
# `git archive`, so the archive holds exactly what the repository tracks — no .git, no __pycache__,
# no editor leftovers, no game data.
#
# Usage:
#   ./release.sh 0.1              # tag 0.1, build the archive, create the GitHub release
#   ./release.sh 0.1 --dry-run    # build the archive into /tmp and stop (no tag, no upload)
#
# Needs a clean tree, `git` and `gh` (logged in).
set -eu

VERSION="${1:-}"
DRY=0
if [ "${2:-}" = "--dry-run" ]; then DRY=1; fi
if [ -z "$VERSION" ]; then
    printf 'usage: %s <version> [--dry-run]      e.g. %s 0.1\n' "$0" "$0" >&2
    exit 2
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
NAME="fgoa-wine-$VERSION"
ARCHIVE="/tmp/$NAME.tar.gz"
NOTES="/tmp/$NAME-notes.md"

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository"
[ -z "$(git status --porcelain)" ] || die "the tree has uncommitted changes — commit them first, a release points at a commit"
command -v gh >/dev/null 2>&1 || die "the 'gh' command is needed to publish the release"

say "release  : $NAME"
say "commit   : $(git rev-parse --short HEAD)  ($(git log -1 --format=%s))"
say "archive  : $ARCHIVE"

rm -f "$ARCHIVE"
git archive --format=tar.gz --prefix="$NAME/" -o "$ARCHIVE" HEAD

# An archive that cannot be installed is worse than none, so check the things the installer needs.
tar -tzf "$ARCHIVE" | grep -qx "$NAME/install.sh"        || die "install.sh is missing from the archive"
tar -tzf "$ARCHIVE" | grep -qx "$NAME/install-sudo.sh"   || die "install-sudo.sh is missing from the archive"
tar -tzf "$ARCHIVE" | grep -qx "$NAME/README.md"         || die "README.md is missing from the archive"
# The PE stub is the launcher's PowerShell shim, and install.sh can only rebuild it where winegcc
# exists: a release without it installs nothing on a machine that has no compiler.
tar -tzf "$ARCHIVE" | grep -qx "$NAME/shim/stub/pwsh-stub.exe" || die "the prebuilt PE stub is missing from the archive"
if tar -tzf "$ARCHIVE" | grep -q '\.git/'; then die "the archive contains .git"; fi
if tar -tzf "$ARCHIVE" | grep -q '__pycache__'; then die "the archive contains __pycache__"; fi
for f in install.sh install-sudo.sh uninstall.sh scripts/launcher.sh shim/pwsh-shim.sh; do
    [ -x "$HERE/$f" ] || die "$f is not executable in the working tree"
done

FILES=$(tar -tzf "$ARCHIVE" | grep -vc '/$')
SIZE=$(du -h "$ARCHIVE" | cut -f1)
SHA=$(sha256sum "$ARCHIVE" | cut -d' ' -f1)
say "contents : $FILES files, $SIZE"
say "sha256   : $SHA"

if [ "$DRY" = 1 ]; then
    say "dry run: nothing tagged, nothing uploaded"
    exit 0
fi

if git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null; then die "tag $VERSION already exists"; fi
git tag -a "$VERSION" -m "fgoa-wine $VERSION"
git push -q origin "$VERSION"
say "tag $VERSION pushed"

cat > "$NOTES" <<EOF
The installer, the patches and the launcher shim for running **Fate/Grand Order Arcade**
(Cloud23333's local platform) with the FGOAC scooby English patch under Wine on Linux, packaged as
one folder.

Unpack it **inside the game folder**, so it sits next to \`App\` and \`Server\` as \`fgoa-wine\`:

\`\`\`bash
tar -xzf $NAME.tar.gz -C /path/to/game/
/path/to/game/fgoa-wine/install.sh
sudo /path/to/game/fgoa-wine/install-sudo.sh   # the only steps that need root
\`\`\`

\`install.sh\` and \`install-sudo.sh\` print what they changed; \`install.sh --verify\` reports the state
of an existing install. **No game data is included** — you need your own assembled game folder
(Cloud23333's 本体 + 前端 1.02 + the FGOAC scooby launcher release). This project is glue for files
you already have, and it is not sold.

**Experimental, and tested on exactly one machine** (CachyOS, wine 11.17, Radeon RX 9070 XT). Another
distribution, another GPU or another Wine build may behave differently. Read
[\`README.md\`](https://github.com/swit33/fgoa-wine/blob/$VERSION/README.md) before starting, and see
[\`docs/UPSTREAM.md\`](https://github.com/swit33/fgoa-wine/blob/$VERSION/docs/UPSTREAM.md) for where
each fix came from. Issues and pull requests are welcome, especially from other hardware and other
distributions.

sha256 \`$NAME.tar.gz\`: \`$SHA\`
EOF

gh release create "$VERSION" "$ARCHIVE" --title "$VERSION" --notes-file "$NOTES"
gh release view "$VERSION" --json tagName,isDraft,url,assets \
    --jq '"published \(.tagName) (draft: \(.isDraft)) \(.url)\nassets: \([.assets[].name] | join(", "))"'
