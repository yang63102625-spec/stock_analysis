# Security Incident: Tushare Token Scrub Runbook

> Status: detected and the **rule file is now scrubbed**, but the previous
> token literal is **still present in git history** and was pushed to the
> remote. This file is the runbook to fully remediate.

## What happened

`.cursor/rules/data-source-priority.mdc` previously contained a hardcoded
Tushare Pro API token in plaintext. That value entered the repository at
commit `2692f76` and was pushed to the remote.

The rule file has since been edited to remove the literal (no longer in
the working tree or HEAD), but git history still contains it on every
commit between `2692f76` and the scrub commit.

## Threat model

- The token is effectively **disclosed**. Treat it as compromised
  regardless of whether anyone scraped GitHub during the exposure window.
- Force-pushing the scrubbed history reduces *future* discovery surface;
  it does **not** retract data that was already cloned, forked, or
  indexed (GitHub search, gharchive, etc).

## Required action (do this first, today)

1. Sign in to the [Tushare console](https://tushare.pro), navigate to
   user / token management, and **regenerate** the API token.
2. Replace the value in your local `.env`:
   ```
   TUSHARE_TOKEN=<new token>
   ```
3. Restart any long-running services (CLI watcher, webui, schedulers).
4. Verify a single fetch works:
   ```bash
   .venv/bin/python -c "from data_provider import DataFetcherManager; \
       print(DataFetcherManager().get_main_indices(region='cn')[:1])"
   ```

The old token is now useless even if it was scraped — this step alone
neutralizes the leak. **Everything below is optional history hygiene.**

## Optional: scrub git history

Force-pushing rewritten history is a **destructive** operation. Do it
only if you accept the consequences listed at the bottom.

### Prerequisites

```bash
brew install git-filter-repo
```

### Step 1 — Mirror backup

Always keep a backup before rewriting history.

```bash
cd ..
git clone --mirror /Users/wei/Projects/tw/stock_analysis stock_analysis.bak.git
cd stock_analysis
```

### Step 2 — Run filter-repo

Replace the leaked literal everywhere it appears in history:

```bash
# Use a placeholder token literal here ONLY for documentation purposes;
# replace ${LEAKED_TOKEN} with the actual 64-char value from your
# personal records (not committed anywhere).
echo "${LEAKED_TOKEN}==>***REDACTED***" > /tmp/scrub.txt
git filter-repo --replace-text /tmp/scrub.txt --force
rm /tmp/scrub.txt
```

`git-filter-repo` will also drop the `origin` remote by design.

### Step 3 — Re-add remote and force push

```bash
git remote add origin <your-remote-url>
git push --force --all origin
git push --force --tags origin
```

### Step 4 — Notify collaborators

Anyone with an existing clone must:

```bash
cd <their clone>
git fetch origin
git reset --hard origin/main      # or whichever branch
# OR simpler: rm -rf the clone and re-clone fresh
```

Open PRs need to be rebased onto the rewritten history, or recreated.

## Consequences of the force push

- All commit hashes change from `2692f76` onward; any external links
  pinning a specific SHA will break.
- CI runs against deleted SHAs in PR history may surface stale failures
  until cleared.
- Existing GitHub forks **retain the leaked token** in their copy of
  history. There is no way to clean forks remotely.
- Any caching mirror (gharchive, sourcegraph snapshots, search indices)
  will likely keep the old data for some time.

## Post-cleanup verification

```bash
# Should print no matches
git log --all -p -S "${LEAKED_TOKEN}"
git grep --cached "${LEAKED_TOKEN}"

# Confirm the rule file is scrubbed in HEAD
grep -c "TUSHARE_TOKEN=" .cursor/rules/data-source-priority.mdc
# expected output: 0
```

## Prevention going forward

- Never paste a real token into a `.cursor/rule/*.mdc`, README, doc, or
  test fixture. Use placeholders (`***REDACTED***`, `<your-token>`).
- Add a pre-commit hook (e.g. `gitleaks` or `detect-secrets`) so
  hex-only strings of suspicious length get flagged before commit.
- Rules that mention secrets must reference the env-var name only, not
  the value (see the current scrubbed `data-source-priority.mdc` §4).
