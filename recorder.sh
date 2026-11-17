#!/bin/sh
# Mirror every GitHub repo of the owner, append new branch/tag tips to refs.txt,
# timestamp the list with an RFC 3161 TSA and OpenTimestamps, then commit and push.
set -eu
export LC_ALL=C

cd "$(dirname "$0")"                 # works no matter where it's run from

LIST=refs.txt                        # public, append-only, committed
TSA_URL=https://freetsa.org/tsr

# One run at a time (the timer and a manual run could overlap).
exec 9> .lock
flock -n 9 || { echo "recorder.sh is already running" >&2; exit 1; }

check() {  # check <cert> <pinfile>
  [ "$(openssl x509 -in "$1" -noout -fingerprint -sha256)" = "$(cat "$2")" ] \
    || { echo "FINGERPRINT MISMATCH: $1" >&2; exit 1; }
}

check cacert.pem cacert.sha256
check tsa.crt    tsa.sha256

touch "$LIST"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# 1. Fetch every repo and append new tips.  A failure in any repo stops the run
#    before stamping, so nothing is stamped from a partial view.  Rows already
#    appended stay, and are stamped by the next successful run.
python3 -I ./coderec.py collect

# 2. Only timestamp/commit if the list differs from what's committed.
#    (Also catches a previous run that died after appending.)
if [ -z "$(git status --porcelain -- "$LIST" 2>/dev/null || echo changed)" ]; then
  echo "Nothing new to timestamp."
  git push -q 2>/dev/null || true    # flush any commits from an offline run
  exit 0
fi
added=$(git diff --numstat -- "$LIST" 2>/dev/null | cut -f1)
[ -n "$added" ] || added=$(wc -l < "$LIST")   # first run: file not tracked yet

# 3. RFC 3161 timestamp of the list.
openssl ts -query -data "$LIST" -sha256 -cert -out "$tmp/refs.tsq"
curl -sSf -H "Content-Type: application/timestamp-query" \
     --data-binary @"$tmp/refs.tsq" "$TSA_URL" -o "$tmp/refs.tsr"
openssl ts -verify -data "$LIST" -in "$tmp/refs.tsr" \
     -CAfile cacert.pem -untrusted tsa.crt
mv "$tmp/refs.tsr" refs.tsr          # only replace the old proof once verified

# 4. Second, independent timestamp (Bitcoin) via OpenTimestamps (ots_mini.py).
#    First save the previous proof's Bitcoin confirmation, if the calendars
#    have it by now, in its own commit; then replace it with a fresh stamp.
#    check_stamps.sh completes the new one once it's in a block (a few hours).
if python3 -I -c 'import opentimestamps' 2>/dev/null; then
  if [ -f "$LIST.ots" ]; then
    python3 -I ./ots_mini.py upgrade "$LIST.ots" >/dev/null 2>&1 || true
    if [ -n "$(git status --porcelain -- "$LIST.ots")" ]; then
      git commit -q -m "Upgrade previous OpenTimestamps proof" -- "$LIST.ots"
    fi
    mv "$LIST.ots" "$tmp/prev.ots"
  fi
  if ! python3 -I ./ots_mini.py stamp "$LIST"; then
    echo "WARNING: OpenTimestamps stamp failed; committing with FreeTSA only" >&2
    if [ -f "$tmp/prev.ots" ]; then mv "$tmp/prev.ots" "$LIST.ots"; fi
  fi
fi

# 5. Commit list + proofs together, so each commit is a verifiable pair.
git add "$LIST" refs.tsr
[ -f "$LIST.ots" ] && git add "$LIST.ots"
git commit -q -m "Record $added tip(s) $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push -q || echo "WARNING: push failed; commit is local, will retry next run" >&2
