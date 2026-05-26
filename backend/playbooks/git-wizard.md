---
name: git_wizard
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /git
---

# Git surgery

Undo, rewrite, split, and salvage commits without losing data.

## Commit surgery

| Goal | Command |
|------|---------|
| Uncommit but keep changes | `git reset --soft HEAD~1` |
| Unstage everything | `git reset` |
| Split one commit into two | `git reset HEAD~1` → stage in groups → `git commit -m "part 1"` → `git commit -m "part 2"` |
| Amend message | `git commit --amend -m "new message"` |
| Add forgotten files | `git add . && git commit --amend --no-edit` |

## Interactive rebase

```bash
git rebase -i HEAD~N      # reword, squash, reorder last N commits
git rebase -i <sha>^       # rebase from a specific ancestor
git rebase --abort         # abort if you mess up
git rebase --continue      # continue after resolving conflicts
```

## Undo and revert

- **Local undo** — `git restore <file>` discard unstaged changes
- **Unstage** — `git restore --staged <file>`
- **Revert a pushed commit** — `git revert <sha>` (safe, adds a new commit)
- **Nuke uncommitted work** — `git checkout -- .` (irreversible — check first with `git diff --stat`)

## Salvage lost work

```bash
git reflog                    # everything you've done, for ~90 days
git cherry-pick <sha>         # pluck a commit onto another branch
git checkout -b rescue <sha>  # create a branch from a lost reflog entry
```

## Bisect

```bash
git bisect start
git bisect bad                # current commit is broken
git bisect good <sha>         # this sha was the last known good
# git will checkout midpoints; run your test and mark:
#   git bisect good   or   git bisect bad
git bisect reset              # done
```

## Example: split the last commit into logical pieces

```bash
git reset HEAD~1              # uncommit, keep staged
git reset                     # unstage everything
git add src/feature-a && git commit -m "feat: add feature A"
git add src/feature-b && git commit -m "feat: add feature B"
```
