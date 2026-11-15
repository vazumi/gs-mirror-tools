#!/usr/bin/env python3
"""Mirror googlesource deps repos to the user's GitHub account.

Runs on GitHub Actions runners (direct googlesource access, fast).
For each repo: create the GitHub repo (public), shallow-fetch the exact
revision from googlesource, push that single commit as refs/heads/mirror.
"""
import json, os, subprocess, sys, time

def sh(cmd, cwd=None, check=True, retry=0):
    for attempt in range(retry + 1):
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
        if attempt < retry:
            time.sleep(5 * (attempt + 1))
            continue
        raise RuntimeError(f"cmd failed ({r.returncode}): {' '.join(cmd)}\nSTDOUT:{r.stdout[-2000:]}\nSTDERR:{r.stderr[-2000:]}")
    raise RuntimeError("unreachable")

def main():
    shard = int(sys.argv[1]); total = int(sys.argv[2])
    owner = sys.argv[3]
    token = os.environ["MIRROR_PAT"]
    plan = json.load(open("plan/mirror-plan-final.json", encoding="utf-8"))
    repos = plan["mirror"][shard::total]
    ok, failed = [], []
    for item in repos:
        name = item["gh_name"]; gs = item["gs_url"]; rev = item["rev"]; kind = item["kind"]
        gh_url = f"https://x-access-token:{token}@github.com/{owner}/{name}.git"
        try:
            # 1. create repo (skip if exists)
            r = subprocess.run(["gh", "api", "-X", "POST", f"/user/repos",
                                "-f", f"name={name}", "-F", "private=false", "-f", "has_issues=false",
                                "-f", "has_projects=false", "-f", "has_wiki=false",
                                "-f", "description=googlesource mirror: " + gs],
                               capture_output=True, text=True,
                               env={**os.environ, "GH_TOKEN": token})
            if r.returncode != 0 and "already_exists" not in r.stderr:
                # 403 rate limit or other; log and continue to fetch anyway
                print(f"[{name}] create: {r.stderr[:300]}", flush=True)
            # 2. shallow fetch from googlesource
            import shutil, tempfile
            with tempfile.TemporaryDirectory() as td:
                sh(["git", "init", "-q", "-b", "mirror"], cwd=td)
                sh(["git", "remote", "add", "origin", gs], cwd=td)
                ref = f"refs/tags/{rev}" if kind == "tag" else rev
                sh(["git", "fetch", "--depth", "1", "--quiet", "origin", ref], cwd=td, retry=2)
                head = sh(["git", "rev-parse", "FETCH_HEAD"], cwd=td).strip()
                # 3. push to GitHub
                sh(["git", "push", "--force", "--quiet", gh_url, f"{head}:refs/heads/mirror"], cwd=td, retry=2)
            ok.append(name)
            print(f"[OK] {name} <- {gs}@{rev[:12]} ({head[:12]})", flush=True)
        except Exception as e:
            failed.append({"name": name, "err": str(e)[-500:]})
            print(f"[FAIL] {name}: {str(e)[-300:]}", flush=True)
        time.sleep(1)
    summary = {"shard": shard, "ok": len(ok), "failed": failed}
    with open(f"summary-{shard}.json", "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary)[:2000], flush=True)
    if failed:
        sys.exit(1)

if __name__ == "__main__":
    main()
