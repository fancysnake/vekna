# Vekna

Vekna watches a tmux session full of running Claude Code instances and
switches focus to whichever pane needs attention. The `vekna` command
starts a server that attaches the session and listens on a Unix socket;
`vekna notify`, run from inside a pane, asks the server to select that
pane so the user lands on the agent that wants them.

## Commands

```bash
mise run start      # dev server :8000
mise run test       # all tests
mise run check      # format + lint
mise run dj <cmd>   # django-admin
```

## URL conventions

### Pages (nouns, trailing slash)

- **url:** `/{namespace}/({subnamespace}/)?{page}/{subpage}/`
- **template:** `/{namespace}/({subnamespace}/)?{page}/{subpage}.html`
- **view:** `({Subnamespace})?{Page}{Subpage}PageView`

### Actions (verbs, `do` prefix, no trailing slash)

- **url:** `/{namespace}/({subnamespace}/)?({page}/{subpage}/)?do/{action}/{subaction}`
- **template:** none
- **view:** `({Subnamespace})?({Page}{Subpage})?{Action}ActionView`

### Components (nouns, `parts` prefix, no trailing slash)

- **url:** `/{namespace}/({subnamespace}/)?({page}/{subpage}/)?parts/{part}`
- **template:** `/{namespace}/({subnamespace}/)?({page}/{subpage}/)?parts/{part}.html`
- **view:** `({Subnamespace})?({Page}{Subpage})?{Part}ComponentView`

## Rules

- Never touch `.env*` files
- NEVER modify, create, or delete configuration files without explicit
  per-case approval.
- NEVER add noqa/type ignore/pylint comments or directives without explicit
  per-case approval.
- When making UI changes, use agent-browser to take screenshots of affected
  pages and include before/after images in the PR description

## Testing

### Structure

```
tests/
  unit/                              # mirrors src/ structure
  integration/
    web/{namespace}/test_{url_name}.py
    cli/test_{command}.py
  e2e/                               # Playwright
  conftest.py
  integration/conftest.py
  integration/utils.py               # assert_response
```

### Unit tests (`tests/unit/`)

- Yes: classes, functions (mills, utilities)
- No: views, commands, repositories
- Write tests in classes
- Mock at the highest level to avoid side effects
- Check all mock calls
- No database access

Repositories are exempt from direct testing — implicitly tested through view
integration tests.

### Integration tests (`tests/integration/`)

- Yes: views, commands
- No: classes, functions
- Use pytest-factoryboy fixtures
- Mock at the lowest level or don't mock if possible
- Check all mock calls and side effects

Always use `assert_response`, never manual assertions:

```python
from http import HTTPStatus
from tests.integration.utils import assert_response

assert_response(
    response,
    HTTPStatus.OK,
    template_name=["namespace/page.html"],
    context_data={...},     # ALL keys, exact equality
    messages=[(messages.SUCCESS, "Saved.")],  # optional
)
```

- Use `ANY` only for hard-to-compare objects (forms, views), never for `[]`,
  `{}`, booleans, or simple values
- Login redirects: exact URL match (`url=f"/crowd/login-required/?next={url}"`)
- Magic numbers: use `1 + 1` pattern with comment (`== 1 + 1  # Email + Phone`)

### E2E tests (`tests/e2e/`)

- Full features, complete user flows

### TDD workflow

Plan -> Tests (red) -> Implement (green) -> Refactor.
Wait for approval between phases.

