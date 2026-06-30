# Merge PR_MYCELIAL_NETWORK Consolidated Package into GitHub

## Recommended repo structure

```text
PR_MYCELIAL_NETWORK/
  README.md
  docs/
    MERGE_TO_GITHUB.md
    VERSION_MANIFEST.json
  data/
    archives/
      PR_MYCELIAL_NETWORK_v1.zip
      ...
      PR_MYCELIAL_NETWORK_v17.zip
  releases/
    PR_MYCELIAL_NETWORK_v17_FINAL_HANDOFF.zip
```

## Option A — GitHub web UI

1. Open the target repository on GitHub.
2. Create folders:
   - `docs/`
   - `data/archives/`
   - `releases/`
3. Upload:
   - `README.md` to repo root.
   - `docs/MERGE_TO_GITHUB.md`
   - `docs/VERSION_MANIFEST.json`
   - all ZIPs from `version_archives/` into `data/archives/`
   - `repo_ready/PR_MYCELIAL_NETWORK_v17_FINAL_HANDOFF.zip` into `releases/`
4. Commit message:

```text
Add PR_MYCELIAL_NETWORK consolidated research handoff
```

## Option B — Git CLI

From your local repo root:

```bash
mkdir -p docs data/archives releases

cp /path/to/PR_MYCELIAL_NETWORK_CONSOLIDATED/README.md ./README.md
cp /path/to/PR_MYCELIAL_NETWORK_CONSOLIDATED/docs/MERGE_TO_GITHUB.md ./docs/
cp /path/to/PR_MYCELIAL_NETWORK_CONSOLIDATED/docs/VERSION_MANIFEST.json ./docs/
cp /path/to/PR_MYCELIAL_NETWORK_CONSOLIDATED/version_archives/*.zip ./data/archives/
cp /path/to/PR_MYCELIAL_NETWORK_CONSOLIDATED/repo_ready/PR_MYCELIAL_NETWORK_v17_FINAL_HANDOFF.zip ./releases/

git add README.md docs/ data/archives/ releases/
git commit -m "Add PR_MYCELIAL_NETWORK consolidated research handoff"
git push
```

## Option C — Create a release

1. Go to GitHub → Releases → Draft a new release.
2. Tag:

```text
pr-mycelial-network-v17
```

3. Release title:

```text
PR_MYCELIAL_NETWORK v17 Final Research Handoff
```

4. Attach:
   - `PR_MYCELIAL_NETWORK_CONSOLIDATED.zip`
   - `PR_MYCELIAL_NETWORK_v17_FINAL_HANDOFF.zip`

## Notes

Keep this repository labeled as research-only. Do not publish precise active/regulated taxon locations or collection guidance.
