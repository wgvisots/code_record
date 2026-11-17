#!/usr/bin/env python3
###########################################################################
# add_headers.py
#
# Copyright 2026 W. Greg Visotski
#
# All rights reserved.
###########################################################################

"""add_headers.py ROOT YEARS LICENSE FILE...

Prepend an astro-style copyright header to each FILE (paths relative to ROOT).
LICENSE: apache | reserved.  Skips files that already name the owner in a
copyright line near the top.  Keeps a leading #! line first.
"""
import collections
import os
import re
import sys

OWNER = "W. Greg Visotski"

APACHE = [
    'Licensed under the Apache License, Version 2.0 (the "License");',
    "you may not use this file except in compliance with the License.",
    "You may obtain a copy of the License at",
    "",
    "        http://www.apache.org/licenses/LICENSE-2.0",
    "",
    "Unless required by applicable law or agreed to in writing, software",
    'distributed under the License is distributed on an "AS IS" BASIS,',
    "WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.",
    "See the License for the specific language governing permissions and",
    "limitations under the License.",
]
RESERVED = ["All rights reserved."]

BLOCK = {".h", ".hpp", ".hh", ".c", ".cc", ".cpp", ".cxx", ".kt", ".kts",
         ".java", ".gradle", ".js", ".ts", ".rs", ".go"}
HASH = {".sh", ".bash", ".py", ".cmake", ".yaml", ".yml", ".toml"}
DASH = {".lua"}


def style(path):
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1].lower()
    if base == "CMakeLists.txt" or ext in HASH:
        return "hash"
    if ext in BLOCK:
        return "block"
    if ext in DASH:
        return "dash"
    return None


def header(kind, title, years, body):
    lines = [title, "", "Copyright %s %s" % (years, OWNER), ""] + body
    if kind == "block":
        out = ["/" + "*" * 70]
        out += [(" * " + l) if l else " *" for l in lines]
        out += [" " + "*" * 70 + "/"]
    elif kind == "hash":
        out = ["#" * 75]
        out += [("# " + l.strip()) if l else "#" for l in lines]
        out += ["#" * 75]
    else:  # lua
        out = ["-" * 75]
        out += [("-- " + l.strip()) if l else "--" for l in lines]
        out += ["-" * 75]
    return "\n".join(out) + "\n"


def main(argv):
    root, years, lic, files = argv[1], argv[2], argv[3], argv[4:]
    body = {"apache": APACHE, "reserved": RESERVED}[lic]
    names = collections.Counter(os.path.basename(f) for f in files)
    done = skipped = 0
    for rel in files:
        kind = style(rel)
        if not kind:
            print("SKIP (no comment style): %s" % rel)
            skipped += 1
            continue
        path = os.path.join(root, rel)
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
        if "\r\n" in text:
            print("SKIP (CRLF): %s" % rel)
            skipped += 1
            continue
        top = "\n".join(text.splitlines()[:40])
        if re.search(r"copyright.*visotski", top, re.I):
            print("SKIP (has header): %s" % rel)
            skipped += 1
            continue
        base = os.path.basename(rel)
        title = rel if names[base] > 1 else base
        shebang = ""
        if text.startswith("#!"):
            shebang, _, text = text.partition("\n")
            shebang += "\n"
        sep = "" if text.startswith("\n") or not text else "\n"
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(shebang + header(kind, title, years, body) + sep + text)
        done += 1
    print("%d file(s) updated, %d skipped" % (done, skipped))


if __name__ == "__main__":
    main(sys.argv)
