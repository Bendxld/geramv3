# Local Source Control security policy

GERAM Source Control operates only on a repository whose worktree and `.git`
directory are contained by the authorized workspace. The renderer never sends
a Git command or free-form argument. Each endpoint maps to a fixed backend
argument template.

Allowed templates are:

- `status --porcelain=v2 --branch -z --untracked-files=all`
- `diff --no-ext-diff --no-textconv` and its `--cached` variant
- `add -- <validated paths>`
- `restore --staged -- <validated paths>`
- `restore --worktree -- <one validated path>`, after preview approval
- `commit --no-verify --no-gpg-sign -m <validated message>`, after preview
- `branch --list --format=<fixed format>`
- `switch <validated branch>` and `switch -c <validated branch>`
- bounded `rev-parse` calls used to validate the repository and commit result

Every invocation uses the trusted system Git executable, `shell=False`, a fixed
working directory, sanitized environment, timeout, output bounds and process
group cleanup. Global and system Git configuration, prompts, pagers, editors,
signing, automatic maintenance and credential interaction are disabled.

## Hooks and executable repository configuration

Commits run with `core.hooksPath=/dev/null`, `--no-verify` and
`--no-gpg-sign`. The empty hooks path applies to every operation, including
branch switches, so repository hooks cannot execute. Repositories are rejected
if local configuration contains filters, custom diff or merge drivers,
includes, credential sections, fsmonitor, external editors, external worktrees
or attribute/exclude files. Executable `filter`, `diff` or `merge` attributes
are rejected. Alternates, common object directories and symlinked Git metadata
are unsupported and fail closed.

There is deliberately no push, pull, fetch, remote management, reset, clean,
checkout force, rebase, amend, cherry-pick, stash or arbitrary command API.
