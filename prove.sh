#!/bin/sh
# prove.sh REPO [COMMIT|BRANCH|TAG...]
# For each commit (default: the repo's default branch on GitHub): the earliest
# recorded tip that contains it, and the FreeTSA and Bitcoin proofs covering it.
exec python3 -I "$(dirname "$0")/coderec.py" prove "$@"
