#!/usr/bin/env python3
"""coderec.py: record and prove when my GitHub repositories' commits existed.

  collect                  mirror every repo of the GitHub owner, append each new
                           branch/tag tip (one that no recorded tip already contains)
                           to refs.txt
  prove REPO [COMMIT...]   earliest recorded tip containing each COMMIT (default: the
                           default branch), plus the FreeTSA and Bitcoin proofs covering it
  copyright [--strict] [--no-fetch] [--owner NAME]...
                           check that every repo's default branch asserts copyright
  digest GITDIR COMMIT     print the SHA-256 tree digest of COMMIT (see README)
  label [--reveal] REPO    print the label used for REPO in refs.txt; --reveal also
                           prints the salt, so one hidden label can be disclosed

Standard library only.  Run with python3 -I.

Exit status: 0 = OK / verified, 1 = error / failed, 2 = pending or couldn't check.
"""
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OWNER = os.environ.get("GH_OWNER", "wgvisots")
LIST = os.path.join(HERE, "refs.txt")          # public, append-only, committed
LABELS = os.path.join(HERE, ".labels")         # local only: per-repo salts for hidden labels
MIRRORS = os.path.join(HERE, "mirrors")        # local only: bare mirrors of every repo
PIN_NS = "refs/recorded/"                      # pins recorded tips so they're never gc'd
LABEL_TAG = "code_record label v1"

FETCH_SPECS = ["+refs/heads/*:refs/remotes/origin/heads/*",
               "+refs/tags/*:refs/remotes/origin/tags/*"]


class Fail(Exception):
    pass


def log(msg):
    print(msg, file=sys.stderr)


def run(cmd, cwd=None, check=True, input=None):
    p = subprocess.run(cmd, cwd=cwd, input=input, capture_output=True)
    if check and p.returncode != 0:
        raise Fail("%s: %s" % (" ".join(cmd[:4]), p.stderr.decode(errors="replace").strip()))
    return p


def git(gitdir, *args, check=True, input=None):
    return run(["git", "--git-dir", gitdir] + list(args), check=check, input=input)


def out(gitdir, *args):
    return git(gitdir, *args).stdout.decode().strip()


# --- GitHub ----------------------------------------------------------------------

def self_name():
    """This record repo's own name on GitHub (never recorded: it changes every run)."""
    p = run(["git", "-C", HERE, "remote", "get-url", "origin"], check=False)
    m = re.search(r"[/:]([^/]+?)(\.git)?$", p.stdout.decode().strip()) if p.returncode == 0 else None
    return m.group(1) if m else os.path.basename(HERE)


def list_repos():
    p = run(["gh", "repo", "list", OWNER, "--limit", "1000", "--json",
             "name,visibility,isFork,isEmpty,defaultBranchRef,sshUrl"], check=False)
    if p.returncode != 0:
        raise Fail("gh repo list failed (is gh logged in?): " + p.stderr.decode().strip())
    repos = json.loads(p.stdout)
    if not repos:
        raise Fail("gh repo list returned no repositories for %s" % OWNER)
    return sorted(repos, key=lambda r: r["name"].lower())


def verified_at(name, sha):
    """GitHub's record of when it first verified this commit's signature."""
    p = run(["gh", "api", "repos/%s/%s/commits/%s" % (OWNER, name, sha),
             "--jq", ".commit.verification.verified_at // \"-\""], check=False)
    v = p.stdout.decode().strip()
    return v if p.returncode == 0 and v else "?"


# --- mirrors ---------------------------------------------------------------------

def mirror_path(name):
    return os.path.join(MIRRORS, name + ".git")


def update_mirror(repo):
    gd = mirror_path(repo["name"])
    if not os.path.isdir(gd):
        os.makedirs(MIRRORS, exist_ok=True)
        run(["git", "init", "-q", "--bare", gd])
        git(gd, "remote", "add", "origin", repo["sshUrl"])
        git(gd, "config", "gc.auto", "0")       # never prune; old tips stay readable
        git(gd, "config", "gc.reflogExpire", "never")
    # --prune only touches refs under refs/remotes/origin/, never the pins.
    git(gd, "fetch", "-q", "--prune", "--no-tags", "origin", *FETCH_SPECS)
    branch = (repo.get("defaultBranchRef") or {}).get("name")
    if branch:  # HEAD = GitHub's default branch, so "HEAD" means what it does there
        git(gd, "symbolic-ref", "HEAD", "refs/remotes/origin/heads/" + branch)
    return gd


def pin(gd, shas):
    if shas:
        git(gd, "update-ref", "--stdin",
            input="".join("update %s%s %s\n" % (PIN_NS, s, s) for s in sorted(shas)).encode())


def remote_tips(gd):
    """Commit IDs of every remote branch and tag (tags peeled to their commit)."""
    fmt = "%(objectname) %(objecttype) %(*objectname) %(*objecttype)"
    tips = set()
    for line in out(gd, "for-each-ref", "--format=" + fmt, "refs/remotes/origin/").splitlines():
        f = line.split()
        if len(f) >= 2 and f[1] == "commit":
            tips.add(f[0])
        elif len(f) == 4 and f[3] == "commit":
            tips.add(f[2])
    return tips


def present(gd, shas):
    """The subset of shas that are commits in this mirror."""
    if not shas:
        return set()
    p = git(gd, "cat-file", "--batch-check=%(objectname) %(objecttype)",
            input=("\n".join(shas) + "\n").encode())
    return {l.split()[0] for l in p.stdout.decode().splitlines() if l.endswith(" commit")}


def is_ancestor(gd, a, b):
    return git(gd, "merge-base", "--is-ancestor", a, b, check=False).returncode == 0


# --- tree digest -----------------------------------------------------------------

def tree_digest(gd, commit):
    """SHA-256 over every file in COMMIT, independent of git's SHA-1:
    for each entry of `git ls-tree -r -z --full-tree COMMIT`, in that order,
    hash  <mode> SP <sha256 of file content> SP <path> NUL
    (submodules: the submodule's 40-hex commit ID in place of the content hash)."""
    listing = git(gd, "ls-tree", "-r", "-z", "--full-tree", commit).stdout
    h = hashlib.sha256()
    cat = subprocess.Popen(["git", "--git-dir", gd, "cat-file", "--batch"],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            meta, path = entry.split(b"\t", 1)
            mode, typ, sha = meta.split(b" ")
            if typ == b"blob":
                cat.stdin.write(sha + b"\n")
                cat.stdin.flush()
                header = cat.stdout.readline().split()
                if len(header) != 3 or header[1] != b"blob":
                    raise Fail("cannot read blob %s" % sha.decode())
                size = int(header[2])
                fh = hashlib.sha256()
                left = size
                while left:
                    chunk = cat.stdout.read(min(left, 1 << 20))
                    if not chunk:
                        raise Fail("short read on blob %s" % sha.decode())
                    fh.update(chunk)
                    left -= len(chunk)
                cat.stdout.read(1)  # trailing newline
                digest = fh.hexdigest().encode()
            elif typ == b"commit":
                digest = sha
            else:
                raise Fail("unexpected tree entry type %r" % typ)
            h.update(mode + b" " + digest + b" " + path + b"\0")
    finally:
        cat.stdin.close()
        cat.wait()
    return h.hexdigest()


# --- labels ----------------------------------------------------------------------

def load_salts():
    salts = {}
    if os.path.exists(LABELS):
        with open(LABELS) as f:
            for line in f:
                if "\t" in line:
                    name, salt = line.rstrip("\n").split("\t", 1)
                    salts[name] = salt
    return salts


def salt_for(name, salts):
    if name not in salts:
        salts[name] = secrets.token_hex(16)
        with open(LABELS, "a") as f:
            f.write("%s\t%s\n" % (name, salts[name]))
            f.flush()
            os.fsync(f.fileno())
    return salts[name]


def hidden_label(name, salt):
    text = "%s\n%s\n%s/%s\n" % (LABEL_TAG, salt, OWNER, name)
    return "h:" + hashlib.sha256(text.encode()).hexdigest()[:32]


def label_for(repo, salts):
    if repo["visibility"] == "PUBLIC":
        return "%s/%s" % (OWNER, repo["name"])
    return hidden_label(repo["name"], salt_for(repo["name"], salts))


# --- the list --------------------------------------------------------------------

def read_list(path=LIST):
    """[(commit, tree_sha256, label, verified_at)] in file order."""
    rows = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                f4 = line.split()
                if len(f4) == 4:
                    rows.append(tuple(f4))
    return rows


def cmd_collect(args):
    repos = list_repos()
    me = self_name()
    salts = load_salts()
    recorded = {r[0] for r in read_list()}
    new_rows, failed = [], []
    for repo in repos:
        name = repo["name"]
        if name == me or repo.get("isEmpty"):
            continue
        try:
            gd = update_mirror(repo)
            tips = remote_tips(gd)
            mine = present(gd, recorded)            # tips of this repo already in the list
            pin(gd, mine)                           # (re)pin: keeps them after force-pushes
            candidates = sorted(tips - mine)
            if not candidates:
                continue
            # Keep only tips not contained in another tip or in a recorded tip.
            indep = set(out(gd, "merge-base", "--independent", *(candidates + sorted(mine))).split())
            fresh = [c for c in candidates if c in indep]
            label = label_for(repo, salts)
            for sha in fresh:
                new_rows.append((gd, sha, "%s  %s  %s  %s" % (
                    sha, tree_digest(gd, sha), label, verified_at(name, sha))))
            if fresh:
                log("%-34s %d new tip(s)" % (name if repo["visibility"] == "PUBLIC" else label, len(fresh)))
        except Fail as e:
            failed.append(name)
            log("ERROR %s: %s" % (name, e))
    if new_rows:
        with open(LIST, "a") as f:
            for _, _, row in new_rows:
                f.write(row + "\n")
            f.flush()
            os.fsync(f.fileno())
        for gd in {r[0] for r in new_rows}:
            pin(gd, {r[1] for r in new_rows if r[0] == gd})
    print("%d repo(s), %d new tip(s) recorded%s" % (
        len(repos), len(new_rows), "; FAILED: " + ", ".join(failed) if failed else ""))
    return 1 if failed else 0


# --- prove -----------------------------------------------------------------------

def rgit(*args, check=True):
    """git in this record repo."""
    return run(["git", "-C", HERE] + list(args), check=check)


def first_recorded():
    """{tip commit: record-repo commit that first added its line}, plus file order."""
    p = rgit("log", "--reverse", "--format=%x00%H", "-p", "--no-color", "--unified=0",
             "--", "refs.txt", check=False)
    first, order, cur = {}, [], None
    for line in p.stdout.decode(errors="replace").splitlines():
        if line.startswith("\0"):
            cur = line[1:]
        elif line.startswith("+") and not line.startswith("+++"):
            f = line[1:].split()
            if len(f) == 4 and f[0] not in first:
                first[f[0]] = cur
                order.append(f[0])
    return first, order


def describe(c):
    s = rgit("log", "-1", "--format=%h  %ad  \"%s\"", "--date=format:%Y-%m-%d %H:%M %z", c).stdout.decode().strip()
    pushed = rgit("branch", "-r", "--contains", c, check=False).stdout.strip()
    url = remote_web_url()
    if pushed and url:
        return s + "\n              %s/commit/%s" % (url, rgit("rev-parse", c).stdout.decode().strip())
    return s + "\n              (NOT PUSHED to GitHub yet)"


_url = []
def remote_web_url():
    if not _url:
        u = rgit("remote", "get-url", "origin", check=False).stdout.decode().strip()
        m = re.match(r"^(?:git@github\.com:|https://github\.com/)(.+?)(?:\.git)?$", u)
        _url.append("https://github.com/" + m.group(1) if m else "")
    return _url[0]


def tsr_imprint(path):
    t = run(["openssl", "ts", "-reply", "-in", path, "-text"], check=False).stdout.decode()
    m = re.search(r"^Message data:\n(.*?)^Serial number:", t, re.S | re.M)
    if not m:
        return ""
    hexes = re.findall(r"^ *[0-9a-f]{4} - (.*)$", m.group(1), re.M)
    return "".join(h.split("   ")[0].replace("-", "").replace(" ", "") for h in hexes)


def tsr_check(data, tsr):
    p = run(["openssl", "ts", "-verify", "-data", data, "-in", tsr,
             "-CAfile", os.path.join(HERE, "cacert.pem"),
             "-untrusted", os.path.join(HERE, "tsa.crt")], check=False)
    if p.returncode == 0:
        t = run(["openssl", "ts", "-reply", "-in", tsr, "-text"], check=False).stdout.decode()
        m = re.search(r"^Time stamp: (.*)$", t, re.M)
        return 0, "verified, signed %s" % (m.group(1) if m else "?")
    return 1, "FAILED: signature or data mismatch"


def ots(*args):
    p = run(["python3", "-I", os.path.join(HERE, "ots_mini.py")] + list(args), check=False)
    return p.returncode, p.stdout.decode().strip()


def have_ots():
    return run(["python3", "-I", "-c", "import opentimestamps"], check=False).returncode == 0


def check_pins():
    for cert, pin in (("cacert.pem", "cacert.sha256"), ("tsa.crt", "tsa.sha256")):
        fp = run(["openssl", "x509", "-in", os.path.join(HERE, cert), "-noout",
                  "-fingerprint", "-sha256"]).stdout.decode().strip()
        with open(os.path.join(HERE, pin)) as f:
            if fp != f.read().strip():
                raise Fail("FINGERPRINT MISMATCH: " + cert)


def file_versions(tmp, path):
    """[(record commit, local copy)] of every committed version of path, oldest first."""
    vs = []
    for c in rgit("rev-list", "--reverse", "HEAD", "--", path, check=False).stdout.decode().split():
        dst = os.path.join(tmp, "%s.%s" % (os.path.basename(path), c))
        p = rgit("show", "%s:%s" % (c, path), check=False)
        if p.returncode == 0:
            with open(dst, "wb") as f:
                f.write(p.stdout)
            vs.append((c, dst))
    return vs


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def resolve(gd, spec):
    for s in (spec, "origin/heads/" + spec, "origin/tags/" + spec):
        p = git(gd, "rev-parse", "--verify", "--quiet", s + "^{commit}", check=False)
        if p.returncode == 0:
            return p.stdout.decode().strip()
    return None


def cmd_prove(args):
    if not args:
        log("usage: prove.sh REPO [COMMIT|BRANCH|TAG...]")
        return 64
    name, specs = args[0], args[1:]
    gd = mirror_path(name)
    if not os.path.isdir(gd):
        log("no mirror for %s (run recorder.sh first, or check the name)" % name)
        return 1
    check_pins()
    specs = specs or ["HEAD"]  # the mirror's HEAD is GitHub's default branch

    first, order = first_recorded()
    rows = {r[0]: r for r in read_list()}
    uncommitted = [s for s in rows if s not in first]
    in_mirror = present(gd, set(rows))
    cands = [s for s in order + uncommitted if s in in_mirror]

    with tempfile.TemporaryDirectory() as tmp:
        lists = file_versions(tmp, "refs.txt")
        list_by_digest = {sha256_file(p): (c, p) for c, p in lists}
        tsrs = [(c, p) for c, p in file_versions(tmp, "refs.tsr")]
        otss = [(c, p) for c, p in file_versions(tmp, "refs.txt.ots")] if have_ots() else []

        status = 0
        for spec in specs:
            target = resolve(gd, spec)
            print("Repo:         %s" % name)
            if not target:
                print("Commit:       %s: NOT FOUND in the mirror\n" % spec)
                status = 1
                continue
            print("Commit:       %s" % target)
            print("              %s  (git's own date; self-asserted)" % out(
                gd, "log", "-1", "--format=%ad  \"%s\"", "--date=format:%Y-%m-%d %H:%M %z", target))
            tip = next((t for t in cands if is_ancestor(gd, target, t)), None)
            if not tip:
                print("Recorded:     NOT COVERED by any recorded tip yet (run recorder.sh)\n")
                status = 1
                continue
            row = rows[tip]
            print("Covered by:   tip %s%s" % (tip, " (the commit itself)" if tip == target else ""))
            digest_ok = tree_digest(gd, tip) == row[1]
            print("Tree SHA-256: %s  %s" % (row[1], "matches" if digest_ok else "MISMATCH"))
            if not digest_ok:
                status = 1
            if row[3] not in ("-", "?"):
                print("GitHub:       signature first verified by GitHub at %s" % row[3])
            if tip not in first:
                print("Recorded:     in refs.txt but NOT COMMITTED yet\n")
                status = 1
                continue
            print("Recorded:     %s" % describe(first[tip]))

            line_prefix = tip + " "

            def containing(digest):
                v = list_by_digest.get(digest)
                if not v:
                    return None
                with open(v[1]) as f:
                    return v if any(l.startswith(line_prefix) for l in f) else None

            text = "FreeTSA:      no proof covers it yet"
            for c, p in tsrs:
                v = containing(tsr_imprint(p))
                if not v:
                    continue
                rc, r = tsr_check(v[1], p)
                if rc == 0:
                    text = "FreeTSA:      %s\n              proof: %s" % (r, describe(c))
                    break
                text = "FreeTSA:      %s (commit %s)" % (r, c[:7])
                status = 1
            print(text)

            if not have_ots():
                print("Bitcoin:      skipped (python3-opentimestamps not installed)")
            else:
                text, pending = "Bitcoin:      no proof covers it yet", False
                for c, p in otss:
                    rc, info = ots("info", p)
                    m = re.search(r"^File sha256 hash: (\w+)", info, re.M)
                    v = containing(m.group(1)) if m else None
                    if not v:
                        continue
                    rc, r = ots("verify", v[1], p)
                    if rc == 0:
                        text = "Bitcoin:      %s\n              proof: %s" % (r, describe(c))
                        break
                    if rc == 1:
                        status = 1
                    if not pending:
                        text = "Bitcoin:      %s\n              proof: %s" % (r, describe(c))
                        pending = True
                print(text)
            print()
    return status


# --- copyright -------------------------------------------------------------------

NOTICE_FILE = re.compile(r"^(licen[cs]e|copying|copyright|notice|readme|authors|unlicense)([._-].*)?$", re.I)
NOTICE_LINE = re.compile(r"(copyright|©|\(c\)).*\b(19|20)\d\d\b|\b(19|20)\d\d\b.*(copyright|©)", re.I)


def notices(gd, commit):
    """[(file, line)] copyright statements in the top-level notice/readme files."""
    found = []
    names = git(gd, "ls-tree", "-z", "--name-only", commit).stdout.decode(errors="replace").split("\0")
    for fn in sorted(n for n in names if n and NOTICE_FILE.match(n)):
        p = git(gd, "cat-file", "-p", "%s:%s" % (commit, fn), check=False)
        if p.returncode != 0:
            continue
        for line in p.stdout[:262144].decode(errors="replace").splitlines():
            # Skip the copyright line of the GPL/LGPL/FDL texts themselves.
            if NOTICE_LINE.search(line) and "Free Software Foundation" not in line:
                found.append((fn, line.strip()))
    return found


def header_notices(gd, commit, owner_re):
    """{path: line} for files anywhere in the tree whose copyright line names an owner."""
    p = git(gd, "grep", "-z", "-I", "-i", "-E", "-e",
            r"(copyright|©|\(c\)).*(19|20)[0-9]{2}", commit, check=False)
    files = {}
    for rec in p.stdout.decode(errors="replace").split("\n"):
        if "\0" not in rec:
            continue
        path, line = rec.split("\0", 1)
        path = path[len(commit) + 1:]
        if owner_re.search(line) and "Free Software Foundation" not in line:
            files.setdefault(path, line.strip())
    return files


def cmd_copyright(args):
    strict = "--strict" in args
    fetch = "--no-fetch" not in args
    owners = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--owner"]
    if not owners:
        n = run(["git", "config", "--global", "user.name"], check=False).stdout.decode().strip()
        owners = [o for o in (n, OWNER) if o]
    owner_re = re.compile("|".join(re.escape(o) for o in owners), re.I)

    counts = {}
    for repo in list_repos():
        name = repo["name"]
        tag = name + (" (fork)" if repo["isFork"] else "") + \
            (" (private)" if repo["visibility"] != "PUBLIC" else "")
        if repo.get("isEmpty") or not repo.get("defaultBranchRef"):
            status, detail = "EMPTY", "nothing to check"
        else:
            branch = repo["defaultBranchRef"]["name"]
            try:
                gd = update_mirror(repo) if fetch or not os.path.isdir(mirror_path(name)) else mirror_path(name)
                tip = resolve(gd, branch)
                if not tip:
                    raise Fail("default branch %s not in mirror" % branch)
                found = notices(gd, tip)
                yours = [f for f in found if owner_re.search(f[1])]
                headers = {} if yours else header_notices(gd, tip, owner_re)
            except Fail as e:
                status, detail = "ERROR", str(e)
            else:
                if yours:
                    status, f = "OK", yours[0]
                elif headers:
                    path = sorted(headers)[0]
                    status, f = "OK", ("%d file header(s), e.g. %s" % (len(headers), path), headers[path])
                elif found:
                    status, f = ("UPSTREAM" if repo["isFork"] else "OTHER"), found[0]
                else:
                    status, f = "MISSING", None
                detail = "%s: %s" % (f[0], f[1][:70]) if f else \
                    "no copyright line in a top-level notice file or in any file header"
        counts[status] = counts.get(status, 0) + 1
        print("%-9s %-36s %s" % (status, tag, detail))

    print()
    print("  ".join("%s %d" % kv for kv in sorted(counts.items())))
    print("(OK = names %s; UPSTREAM/OTHER = a notice naming someone else only)" % " or ".join(owners))
    bad = {"MISSING", "ERROR"} | ({"UPSTREAM", "OTHER"} if strict else set())
    return 1 if any(counts.get(s) for s in bad) else 0


# --- small helpers ---------------------------------------------------------------

def cmd_digest(args):
    if len(args) != 2:
        log("usage: coderec.py digest GITDIR COMMIT")
        return 64
    gd = run(["git", "-C", args[0], "rev-parse", "--absolute-git-dir"]).stdout.decode().strip()
    print(tree_digest(gd, out(gd, "rev-parse", "--verify", args[1] + "^{commit}")))
    return 0


def cmd_label(args):
    reveal = "--reveal" in args
    names = [a for a in args if a != "--reveal"]
    if len(names) != 1:
        log("usage: coderec.py label [--reveal] REPO")
        return 64
    name = names[0]
    vis = next((r["visibility"] for r in list_repos() if r["name"] == name), None)
    if vis is None:
        log("%s/%s not found on GitHub" % (OWNER, name))
        return 1
    salts = load_salts()
    if vis == "PUBLIC":
        print("%s/%s  (public: shown by name)" % (OWNER, name))
    if name in salts or vis != "PUBLIC":
        salt = salt_for(name, salts)
        print(hidden_label(name, salt) + ("  (used while it was private)" if vis == "PUBLIC" else ""))
        if reveal:
            print("salt: %s" % salt)
            print("check: printf '%s\\n%%s\\n%s/%%s\\n' %s %s | sha256sum | cut -c1-32"
                  % (LABEL_TAG, OWNER, salt, name))
    return 0


COMMANDS = {"collect": cmd_collect, "prove": cmd_prove, "copyright": cmd_copyright,
            "digest": cmd_digest, "label": cmd_label}


def main(argv):
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 64
    try:
        return COMMANDS[argv[1]](argv[2:])
    except Fail as e:
        log("error: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
