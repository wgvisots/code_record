#!/bin/sh
# copyright_check.sh [--strict] [--no-fetch] [--owner NAME]...
# Check that every GitHub repo's default branch has a copyright notice in a
# top-level LICENSE / COPYING / COPYRIGHT / NOTICE / README file.
# Exit 1 if any repo has none (with --strict, also if a notice doesn't name you).
exec python3 -I "$(dirname "$0")/coderec.py" copyright "$@"
