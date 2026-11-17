# Code authenticity record

A public, append-only list of the commits at the tips of every branch and tag
in my GitHub repositories (`wgvisots`), with independent timestamps proving
each one existed by a given date.

A git commit ID covers the commit's files and its entire history, so one
recorded tip proves that everything before it existed too. Git's own commit
dates prove nothing (anyone can write any date); the timestamps are what count.

This is the code counterpart of the photo record
(`~/Pictures/not_bad/record`) and shares its timestamping parts.

## How it works

1. **`recorder.sh`** lists every repo of `wgvisots` with `gh`, fetches each one
   into a local mirror, and appends every new branch or tag tip to `refs.txt`.
   A tip that an already-recorded tip contains is skipped, since it's already
   proven. This repo itself is never recorded.
2. The whole list is timestamped twice, just as for the photos:
   - **FreeTSA** (RFC 3161): a signed reply, `refs.tsr`, available right away.
   - **OpenTimestamps** (Bitcoin): `refs.txt.ots`, pending for a few hours
     until it is included in a Bitcoin block.
3. The list and both proofs are committed together and pushed to GitHub. Old
   versions stay in git history, so every tip keeps the proof from the day it
   was recorded.

A proof shows a commit **existed by** that date. Authorship rests on the rest
of the evidence: signed commits, a long history of small commits, copyright
notices, and being first.

## Everyday use

It runs by itself once the timers are installed (see below). By hand:

```sh
./recorder.sh                  # fetch all repos, record new tips, timestamp, commit, push
./check_stamps.sh              # a few hours later: finish the Bitcoin proof, check GitHub
./prove.sh astro               # proof for astro's default branch
./prove.sh astro a8f7c44 v1.2  # proof for particular commits, branches or tags
./copyright_check.sh           # does every repo assert copyright?
```

Example:

```
$ ./prove.sh astro a8f7c44
Repo:         astro
Commit:       a8f7c44...
              2026-11-15 22:12 -0600  "..."  (git's own date; self-asserted)
Covered by:   tip a8f7c44... (the commit itself)
Tree SHA-256: 5e0c...  matches
GitHub:       signature first verified by GitHub at 2026-11-16T04:13:05Z
Recorded:     1a2b3c4  2026-11-16 ...  "Record 61 tip(s) ..."
FreeTSA:      verified, signed Nov 16 ... 2026 GMT
Bitcoin:      verified, Bitcoin block 972xxx (...)
```

**"NOT COVERED"** means no recorded tip contains that commit yet. It is new
since the last run, or it was never pushed to GitHub.

## Commands

| Command | What it does |
|---|---|
| `recorder.sh` | Fetch every repo, append new tips, timestamp the list, commit and push. Stops without stamping if any repo can't be fetched. |
| `check_stamps.sh` | Check the current FreeTSA reply, fetch and verify the Bitcoin proof (committing and pushing it once complete), and confirm everything is on GitHub. Exits 0 only when all three are good. |
| `prove.sh REPO [COMMIT...]` | For each commit (default: the default branch): the earliest recorded tip containing it, a re-check of that tip's tree digest, and the earliest FreeTSA and Bitcoin proofs covering it, with GitHub links. |
| `copyright_check.sh` | For each repo's default branch, look for a copyright line (the word *copyright*, *©* or *(c)* plus a year): first in top-level `LICENSE`, `COPYING`, `COPYRIGHT`, `NOTICE`, `README` or `AUTHORS` files, then in file headers anywhere. See below. |
| `coderec.py digest GITDIR COMMIT` | Print a commit's SHA-256 tree digest. |
| `coderec.py label [--reveal] REPO` | Print the label a repo has in `refs.txt`; `--reveal` adds its salt, to disclose that one label. |

Exit status: `0` = OK / verified, `1` = error / failed, `2` = pending or couldn't check.

## `refs.txt`

One line per recorded tip, append-only:

```
<commit ID>  <tree SHA-256>  <label>  <GitHub verified_at, or ->
```

- **Commit ID**: git's SHA-1 commit ID. It covers the commit's files and all its history.
- **Tree SHA-256**: a digest of every file in that commit, so the record doesn't
  rest on SHA-1 alone (SHA-1 collisions are known to be possible). For each entry
  of `git ls-tree -r -z --full-tree COMMIT`, in that order, it hashes
  `<mode> <sha256 of the file's content> <path>` followed by a NUL byte
  (for a submodule, the submodule's 40-hex commit ID replaces the content hash).
- **Label**: `wgvisots/<name>` for public repos. Private repos get a hidden label,
  `h:` plus 32 hex characters, so their names aren't published. Each hidden label
  uses its own random salt, kept in `.labels` (local only), so one can be
  disclosed without exposing the others:
  `printf 'code_record label v1\n%s\nwgvisots/%s\n' SALT NAME | sha256sum | cut -c1-32`.
  If a private repo becomes public, later lines use its name and earlier lines
  keep the hidden label. `prove.sh` doesn't need the labels: it matches by
  commit history.
- **verified_at**: when GitHub first verified the commit's signature (GitHub's
  own server-side record, copied here when the tip was recorded). `-` = not
  signed, or GitHub hasn't verified it. `?` = GitHub couldn't be asked.

## Verifying without these scripts

Anyone can check a commit with standard tools:

1. Clone the repo, and check that the commit in question is an ancestor of a
   commit ID listed in `refs.txt`: `git merge-base --is-ancestor COMMIT TIP`.
   The commit history of `refs.txt` on GitHub shows when each line was added.
2. Optionally recompute the tree digest (bash):
   ```bash
   git ls-tree -r -z --full-tree TIP | while IFS= read -r -d '' e; do
     set -- ${e%%$'\t'*}; p=${e#*$'\t'}
     if [ "$2" = blob ]; then d=$(git cat-file blob "$3" | sha256sum | cut -c1-64); else d=$3; fi
     printf '%s %s %s\0' "$1" "$d" "$p"
   done | sha256sum
   ```
3. FreeTSA: download `refs.txt`, `refs.tsr` and the certificates from the same commit, then:
   `openssl ts -verify -data refs.txt -in refs.tsr -CAfile cacert.pem -untrusted tsa.crt`
   (get `cacert.pem` and `tsa.crt` from freetsa.org directly for an independent check).
4. Bitcoin: drop `refs.txt` and `refs.txt.ots` into the verifier at opentimestamps.org,
   or run `ots verify` with the official client and a Bitcoin node.

## Copyright check

`copyright_check.sh` reports, for each repo:

| Status | Meaning |
|---|---|
| `OK` | A copyright line names you (`git config user.name`, or `wgvisots`), in a top-level notice file or in the header of any text file. |
| `UPSTREAM` | A fork whose only notice names someone else (normal for a fork; add your own for your changes). |
| `OTHER` | Not a fork, but the only notice names someone else. |
| `MISSING` | No copyright line found anywhere. |
| `EMPTY` | The repo has no commits. |

It exits 1 if any repo is `MISSING` (or couldn't be checked). With `--strict`
it also fails on `UPSTREAM` and `OTHER`. `--owner NAME` (repeatable) changes
who counts as you. `--no-fetch` uses the mirrors as they are. It checks
GitHub's default branch, so commit and push a new notice before re-checking.

A notice can be as short as a `COPYRIGHT` file with
`Copyright (c) 2026 Your Name. All rights reserved.`, or a LICENSE whose
copyright line names you.

### Adding headers

`add_headers.py ROOT YEARS LICENSE FILE...` puts a copyright header at the top
of each FILE (paths relative to ROOT), in the same style as astro's: a banner
with the file's name (or its path, if the name appears more than once), the
copyright line, then the license notice. `LICENSE` is `apache` (Apache 2.0
notice) or `reserved` ("All rights reserved."). For example, in a repo:

```sh
git ls-files | grep -E '(\.(h|hpp|c|cpp|kt|kts|java|gradle|sh|py)|(^|/)CMakeLists\.txt)$' \
  | xargs ~/git/code_record/add_headers.py . 2026 apache
```

- C, C++, Kotlin, Java, Gradle and similar files get a `/* ... */` block;
  shell, Python, CMake and YAML files get `#` lines; Lua gets `--` lines.
  Other types are skipped.
- A `#!` line stays first. Files with Windows line endings are skipped.
- Files that already name the owner in a copyright line near the top are
  skipped, so it is safe to run again.
- Check first for code copied from someone else: that needs a header crediting
  its author, not a plain copyright claim (see `init.lua` in nvim_config).

## Running it daily

```sh
mkdir -p ~/.config/systemd/user
cp systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now code-record.timer code-record-check.timer
systemctl --user list-timers 'code-record*'      # next run times
journalctl --user -u code-record.service         # output of past runs
```

`code-record.timer` runs `recorder.sh` daily, and `code-record-check.timer`
runs `check_stamps.sh` each morning to complete the Bitcoin proof. Both catch up
after the machine was off. They need the SSH key (for fetching and commit
signing) and `gh`'s login to work without a prompt.

## Files

| File | Purpose |
|---|---|
| `refs.txt` | Recorded tips (see above), append-only |
| `refs.tsr` | FreeTSA signed timestamp of `refs.txt` |
| `refs.txt.ots` | OpenTimestamps (Bitcoin) proof of `refs.txt` |
| `cacert.pem`, `tsa.crt` | FreeTSA certificates, needed to verify `.tsr` files |
| `*.sha256` | Pinned fingerprints of those certificates; the scripts stop if they change |
| `coderec.py` | Fetching, recording, proving and the copyright check (standard library only) |
| `add_headers.py` | Adds copyright headers to source files (see "Adding headers") |
| `common.sh`, `ots_mini.py` | Shared with the photo record (see its README) |
| `systemd/` | User timer units |
| `mirrors/` | Local only: a bare mirror of every repo. Recorded tips are pinned under `refs/recorded/` and never pruned, so they stay provable after a force-push or a deleted branch. Also a backup. |
| `.labels` | Local only: salts for hidden labels. **Back this up**: without it, a hidden label can't be tied to its repo (proofs still work). |

## Troubleshooting

- **A repo failed to fetch:** nothing is stamped that run. Fix access (`gh auth
  status`, `ssh -T git@github.com`) and run `recorder.sh` again. Tips already
  appended are stamped then.
- **Push rejected:** if `main` is protected with "signatures required", every
  commit must be signed. Check that `git config commit.gpgsign` is `true`.
- **`FINGERPRINT MISMATCH`:** a FreeTSA certificate file changed. Don't continue
  until you know why (see the photo record's README).
- **A repo was renamed:** it is mirrored again under its new name. Its old
  mirror keeps its pins.
- **Moved or lost `mirrors/`:** the next run fetches everything again. Tips that
  are gone from GitHub (force-pushed away) can then only be proven from another
  copy of the repo.
