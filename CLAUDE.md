# CLAUDE.md

Boxes Boxes Boxes: a personal tool for recording which numbered box a thing ended up in.

## The two documents that govern this repo

- **`SPEC.md` is the contract.** It is precise about the HTTP API and the data model, and
  deliberately loose about everything else. When code and spec disagree, the spec wins,
  or the spec gets changed deliberately, not drifted away from.
- **`PLAN.md` is the build order.** Numbered steps, each ending in a verification. A step
  is not finished until its Verify block passes.

Read the relevant spec section before implementing a step. Do not re-derive decisions
that §3 already records as settled.

## Repositories

| Path | Role |
|---|---|
| `.` (this repo) | The application. Distribution and Python package `boxes3`. |
| `../pylib` | Reusable components, currently just the blob store. Separate public repo at `github.com/brasse/pylib`, consumed from tag `v0.1.0`. |
| `../no-more-paper-2` | **Read-only.** See below. |

### `no-more-paper-2` is read-only

An unfinished separate project the author intends to return to. **Never write to it, fork
it, or modify it.** Not a file, not a formatting fix, not a lint pass. It is reference
material only (§2.1, §12): read it for patterns, copy code out of it, change nothing in it.

The blob store was *copied* out of it into `pylib`, not moved. The duplication is
intentional.

## Commands

```
uv sync                # install
uv run fastapi dev src/boxes3/main.py   # run it (no config needed on a
                                              # fresh clone; the CLI cannot find
                                              # an app under src/<package>/ on
                                              # its own, so the path is required)
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run basedpyright    # type check
uv run alembic upgrade head    # the app does this itself on startup
```

Frontend (once it exists), from `frontend/`:

```
npm run dev            # Vite dev server, proxies /api to the backend
npx tsc --noEmit       # type check
make types             # regenerate API types from the running app's /openapi.json
```

## Conventions

Ruff and basedpyright are the quality gate. Ruff runs `E,F,I,B,UP,ANN,FAST` with `ANN`
relaxed for tests, which checks that annotations exist. basedpyright checks that they are
right, in `standard` mode with `reportDeprecated` raised to an error. It is the same
engine as Pylance, so the editor and CI agree.

**Tests ship with the code they test, in the same change** (§10). Not deferred to a later
pass, not offered afterwards. A step that adds behaviour and no test is unfinished.

Everything else is specified in `SPEC.md`: the storage layer's abstract base class, the
identifier rules, the error envelope, the search contract. Follow it there rather than
guessing from surrounding code.

## Python, not Java

This is a Python project. Global rules written for a Java monorepo do not apply here:
`var`, typed URI wrappers, gRPC `Status`, bazel targets, Maven.
