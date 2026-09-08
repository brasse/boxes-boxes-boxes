# Build Plan

Implementation plan for `SPEC.md`. Section references (§) point into that document,
which remains the contract. This file only says in what order it gets built and how
each step is checked.

**How this works.** Every step below is a self-contained increment ending in a
verification you can run yourself. A step is finished when its **Verify** block passes,
tests included (§10: tests ship with the code they test). Nothing moves on before then.

Two repositories are involved:

| Path | Repo |
|---|---|
| `~/github/pylib` | `pylib`: new, public on github.com |
| `~/github/boxes-boxes-boxes` | the application; distribution and package `boxes3` |

`~/github/no-more-paper-2` is read-only reference material (§2.1). Nothing writes to it.

---

## Phase 0: `pylib`

### Step 0.1: Create the `pylib` repository

Deliverable: the layout in §2.2, meaning `pyproject.toml`, `src/pylib/blobstore/`
(`blob_store.py`, `filesystem.py`, an empty `__init__.py`), `tests/`. Code copied out
of `no-more-paper-2`, with all `no_more_paper` imports renamed and no inventory
vocabulary anywhere in the API.
Ruff config and `dev` group (pytest, pytest-asyncio) carried over from the reference
`pyproject.toml`.

Verify:
- `cd ~/github/pylib && uv run pytest && uv run ruff check .` is clean.
- `git log` shows one commit; nothing under `~/github/no-more-paper-2` changed
  (`git -C ~/github/no-more-paper-2 status` clean).

### Step 0.2: Atomic `put`, plus `tmp_dir`

Deliverable: `put` writes to a temp file, `fsync`s, then `os.replace`s onto the final
path (§2.2). `FileSystemBlobStore` gains an optional `tmp_dir` defaulting to the store
root; a `tmp_dir` on a different filesystem is rejected at construction, since
`os.replace` would not be atomic. The store stays dumb: no hashing, no verification,
overwrite permitted.

Tests (§10): a concurrent reader never observes a partial file; overwriting an existing
id replaces it cleanly rather than truncating in place; no stray temp files survive a
successful write; a failed write leaves the previous blob intact.

Verify:
- `uv run pytest && uv run ruff check . && uv run basedpyright` is clean.
- The partial-read test genuinely fails if you revert `put` to `path.write_bytes`.
  I will demonstrate this rather than assert it.

### Step 0.3: CI and tag `v0.1.0`

Deliverable: `.github/workflows/ci.yml` that installs with `uv` and runs `ruff check`
and `pytest`, on push and PR (§10). Then `git tag v0.1.0 && git push --tags`.

Verify:
- `gh run list` (or the Actions tab) shows a green run for the tagged commit.
- From a scratch directory, `uv add "pylib @ git+https://github.com/brasse/pylib@v0.1.0"`
  resolves and installs.

---

## Phase 1: Application foundations

### Step 1.1: Project skeleton and configuration

Deliverable: `pyproject.toml` with the §2.3 dependency set (`pylib` pinned to the
`v0.1.0` git tag), ruff, pytest, `src/boxes3/`, and CI mirroring `pylib`'s.
Configuration per §9: `$DATA_DIR/config.toml` (default `./data`), created on first run
with a generated `secret_key`, written atomically and mode `0600`; `secret_key`,
`backup_token`, `session_cookie_secure` (default `false`) each overridable by environment
variable. Reading the configuration writes nothing by itself: `Config.load` reads the
file and the environment, and the startup sequence generates a key and calls `save`
explicitly. `backup_token` is set
by editing the file, with no command for it (§9). A `.gitignore` covering `data/`. A
minimal FastAPI app that starts and serves `/openapi.json`.

Verify:
- `rm -rf data && uv sync && uv run fastapi dev src/boxes3/main.py` on a clean
  checkout starts with no configuration, creates `data/`, `data/blobs/`, `data/tmp/`
  and `data/backup/`, plus a `config.toml` holding a `secret_key` and no `backup_token`.
- Restarting does not regenerate the key.
- `SECRET_KEY=x uv run ...` wins over the file.
- `Config.load()` on a fresh data directory creates nothing at all.
- `git status` is clean after a run, i.e. `data/` is ignored.
- `uv run pytest && uv run ruff check . && uv run basedpyright` is clean.

### Step 1.2: Schema, pragmas, Alembic

Deliverable: the §7.3 tables as dialect-neutral SQLAlchemy Core `Table` objects on one
shared `MetaData`, including the `CHECK`s, the composite `UNIQUE (user_id, number)`, the
`ON DELETE RESTRICT` on `items.box_id` and the extra indexes. A `connect` event listener
applying all four pragmas of §7.2. Alembic configured, with the initial migration
authored from that metadata; **the app applies migrations on startup**, and
`create_all()` appears only in tests (§7.5).

Verify:
- `uv run alembic upgrade head` against an empty file produces every table and index;
  `uv run alembic downgrade base` reverses it.
- A test opens a temp-**file** database (not `:memory:`, §10) and asserts
  `foreign_keys=1`, `journal_mode=wal`, `synchronous=1`, `busy_timeout=5000`.
- A test asserts deleting a box that holds items raises, i.e. `RESTRICT` is genuinely
  enforced, which it is not if the pragma is missing.
- `sqlite3 data/inventory.db .schema` reads as expected.

### Step 1.3: `InventoryDatabase` ABC and boxes

Deliverable: the abstract base class in domain terms with domain exceptions
(`BoxNotFoundError`, `BoxNumberTakenError`, …), and `SqliteInventoryDatabase`
implementing the user and box halves: create/get/list/update/delete box, next free
number, distinct locations, `item_count`. Public ids from `secrets.choice` over base62,
16 chars. Cursor pagination and `total`. No SQL outside the implementation class (§7.4).

Verify:
- Database-level pytest suite: number uniqueness per user, `next_number` skips gaps
  correctly, `q` matches number/name/location, ordering by `number` ascending,
  pagination walks a >50-row set exactly once with no duplicates or gaps,
  delete-non-empty raises, forced delete removes items in one transaction.
- `uv run pytest && uv run ruff check . && uv run basedpyright` is clean.

### Step 1.4: Items in the database layer

Deliverable: item create/get/update/delete/move, tag normalisation (trim, lowercase,
dedupe, the `[a-z0-9-]` and count/length limits of §4), tag listing with counts, and
search: case-insensitive `LIKE` over title and tags, with `tag` (conjunctive), `box`
and `has_image` filters composing on top, `updated_at` descending, cursor paginated
with `total`.

Verify:
- Search suite written as the **behavioural contract** of §10, so it can be re-run
  unchanged against FTS5 later: this query finds that item, filters compose, `tag` is
  conjunctive, order is server-defined.
- Tag normalisation tests, including rejection of over-long and illegal tags.
- `total` is the count across all pages, not the page size.

---

## Phase 2: HTTP API

### Step 2.1: Error envelope, sessions, login

Deliverable: exception handlers translating `HTTPException`,
`RequestValidationError` and unhandled exceptions into the single §6.0 envelope, with
the status table wired to stable `code` strings. Session cookie per §5, signed,
carrying **username** and expiry, `HttpOnly`, `SameSite=Lax`, configurable `Secure`,
30-day `Max-Age` refreshed on use. `get_current_user` dependency; `401` on everything
under `/api` except login and admin backup. `python -m boxes3.set_password
<username>` creating or updating a scrypt hash, prompting interactively, printing no
password. Startup logs the instruction when `users` is empty.

Verify:
- `uv run python -m boxes3.set_password brasse` prompts, stores a hash, prints
  nothing sensitive; running it again updates rather than duplicates.
- `curl -i -X POST .../api/auth/login` with good credentials returns `204` and a
  `Set-Cookie`; with bad ones, `401` in the envelope shape.
- `curl .../api/auth/me` with the cookie returns `{"username": "brasse"}` and **no**
  `user_id`.
- A test asserts all three error sources (raised `HTTPException`, a validation failure,
  an unhandled exception) produce the identical envelope.

### Step 2.2: Box endpoints

Deliverable: the seven routes of §6.2, request/response Pydantic models exposing the
external id as `id`, `PATCH` semantics (omitted unchanged, explicit `null` clears),
`409 box_number_taken`, `409 box_not_empty` and `?force=true`.

Verify: API tests through `httpx.AsyncClient` covering each status code, plus a manual
`curl` walk-through creating a box, renumbering it into a collision, and force-deleting
a non-empty one.

### Step 2.3: Item and tag endpoints

Deliverable: §6.3 routes plus `GET /api/tags`. `box_id` in bodies is a box's **public**
id, resolved to the internal key inside the database layer.

Verify: API tests for CRUD, move-by-`box_id`, `404 box_not_found` on an unknown box,
every search parameter, and unpaginated `/api/tags` ordered by count descending.

### Step 2.4: Images

Deliverable: the §6.4 routes and the pipeline of §4. SHA-256 of the upload becomes
`image_key`; `original` stored byte-identical with its MIME type recorded; `full`
(2048px) and `thumb` (320px) derived as JPEG with EXIF orientation applied and remaining
metadata stripped; HEIC decoded via `pillow-heif`. Blob written and durable **before**
the row is committed. `PUT` repoints rather than overwrites; `DELETE` clears the key and
leaves bytes in place. Cache headers per variant (§6.4); `v` ignored entirely.

Verify:
- Tests per §10: each accepted format including a real HEIC fixture, a portrait photo
  with an orientation tag, `413` over 20 MB, `415` for an unsupported type. The one that
  matters most: the stored `original` is **byte-identical** to the upload.
- `curl -o out.jpg '.../image?variant=original'` on a HEIC upload returns
  `Content-Type: image/heic` and bytes matching the source file's `sha256sum`.
- Response headers show `immutable` for `original`, `max-age=86400` for the others.

### Step 2.5: No internal identifiers in any response

Deliverable: the §10 test that walks every endpoint's JSON and asserts no `user_id` and
no `id` that parses as an integer, anywhere, at any depth.

Verify: the test passes, and demonstrably fails if `user_id` is added to a response
model. Placed after the API is complete so it covers all of it at once.

### Step 2.6: Backup endpoint

Deliverable: `POST /api/admin/backup` per §7.6, bearer-token authenticated, disabled
when unconfigured, `VACUUM INTO` a temp file, fsync, `os.replace` into
`/data/backup/inventory.db`, a lock giving `409 backup_in_progress` to a concurrent
call.

Verify:
- The end-to-end test of §10: write data, call the endpoint, restore the snapshot into a
  fresh data directory following the §7.6 restore steps, assert the data is present.
- Concurrent calls: one `200`, one `409`.
- Unset token ⇒ endpoint disabled; wrong token ⇒ `401`.

### Step 2.7: `gc` and `regenerate_images`

Deliverable: the two commands of §4 and §7.6, both with `--dry-run`.

Verify:
- `gc` tests: removes orphans, never removes a referenced blob, and specifically handles
  two items sharing one `image_key` (§7.3).
- `regenerate_images` test: `image_key` unchanged, `original` byte-identical, `full` and
  `thumb` replaced.
- `--dry-run` writes and deletes nothing, asserted by comparing the blob tree before
  and after.

---

## Phase 3: Frontend

Build order is laptop-first (§8 Rules), while the CSS is authored narrow-first.

### Step 3.1: Scaffold, generated types, login

Deliverable: Vite + React + TS, dev server proxying `/api` so the browser sees one
origin. A `make` target running `openapi-typescript` against `/openapi.json`, output
committed. A thin `fetch` wrapper setting `credentials: "include"` and unwrapping the
§6.0 error envelope, including the §6.0 note that an unparseable failed upload is
treated as "too large". Login screen with username and password fields and correct
`autocomplete` hints.

Verify:
- `npm run dev`, log in, land on an empty home; reload keeps you logged in; logout
  returns you to login.
- `make types` regenerates with no diff when the backend is unchanged.
- `npx tsc --noEmit` passes on a fresh checkout with no backend running.

### Step 3.2: Search and item detail

Deliverable: the home screen, with a search field focused on load, 250 ms debounce,
results showing title, box number, box location and thumbnail, tag filter chips, cursor
pagination. Item detail with full image, metadata, edit/move/delete. Master-detail above
900px, stack navigation below, **selection held in the URL** (`/search?q=…&item=<id>`).
No client-side re-sorting.

Verify:
- Narrow the window past 900px and back: layout switches, no state is lost.
- Deep-link `/search?q=drill&item=<id>` in a fresh tab: correct on both layouts.
- Browser Back behaves on both sides of the breakpoint.
- Thumbnails carry `&v=<image_key>`; replacing a photo updates the image immediately.

### Step 3.3: Boxes

Deliverable: box list, box detail with its items (via `GET /api/items?box=`), add/edit
box with `number` pre-filled from `next-number` and location autocomplete from
`GET /api/boxes/locations`.

Verify: create a box, add items, edit its number and location, attempt a delete while
non-empty and see the confirm dialog showing the item count.

### Step 3.4: Pack a box

Deliverable: the §8 bulk-entry mode. Box chosen once, Enter submits and refocuses
title, tags persist between entries and are individually removable, optional photo that
never blocks, a running session list with per-row undo, optimistic insertion.

Verify: enter ten items with the keyboard alone, no mouse. Undo one. Confirm the box
stays fixed throughout and that entry speed is not gated on the server round trip.

### Step 3.5: Add item

Deliverable: the phone flow of §8. Title, searchable box picker (by number, name and
location), tag autocomplete, photo taken inline with
`<input type="file" accept="image/*" capture="environment">`, background upload with a
visible progress indicator, no client-side downscaling.

Verify: on your phone over the tailnet, add one item with a photo in a single pass
without the UI blocking during upload.

### Step 3.6: Photo pass

Deliverable: the per-box queue of §8 backed by
`GET /api/items?box=<id>&has_image=false`, counters from the envelope's `total`, Skip,
auto-advance, optimistic upload, and a "boxes with photo-less items" entry point.

Verify: on the phone, photograph three items in a row; close the browser mid-queue and
reopen. The queue resumes from server state with the finished items gone.

### Step 3.7: Cross-cutting frontend requirements

Deliverable: `401` redirects to login preserving the intended destination; every list
paginates via `next_cursor`; 44px touch targets below the breakpoint; nothing essential
behind hover; navigation hides "pack a box" on the phone and the photo pass on the
laptop while both routes still resolve everywhere (§8, "Hide affordances, never hide
capability"); the smoke test of §10.

Verify: expire the cookie mid-session and confirm the redirect returns you to where you
were. Open `/pack/<box>` on the phone, cramped but working, not a dead end.

---

## Phase 4: Deployment

### Step 4.1: Docker image

Deliverable: a multi-stage Dockerfile. Frontend built at image build time, static
output served by FastAPI, one service, one port, no CORS. `pylib` installed from the
public git tag (no credentials needed). `DATA_DIR=/data`, one volume.

Verify:
- `docker build .` succeeds on a clean clone with no host network mounts beyond the
  registry and github.com.
- `docker run -v ./data:/data -p 8000:8000` comes up, and the app is usable from the
  phone over the LAN.
- `du -sh` the volume and confirm the §9 layout is exactly what is there.

### Step 4.2: README, Caddy, backup rehearsal

Deliverable: README stating plainly that plain HTTP is supported, that localhost is a
secure context, and that the only limitation is milestone-2 features when reaching a
plain-HTTP server from another device (§9). A sample Caddy block, and the two-line
backup procedure of §7.6 as a script.

Verify:
- The §7.6 restore procedure performed **once, deliberately, by hand** against a real
  snapshot on a scratch directory, since the spec asks for this explicitly and the
  automated test in step 2.6 does not replace it.
- Behind Caddy with `session_cookie_secure = true`, log in from the phone over HTTPS.

---

## Notes carried from reading the spec

- §8 "On snappy" lists client-side downscaling among the milestone-1 requirements. §4
  and §8 "Requirements" both forbid it, twice, with reasons. **No downscaling** is what
  gets built.
- §12's paths have drifted from `no-more-paper-2` as it stands: the patterns cited as
  `db/document_database.py` and `db/sqlite/document_database.py` are actually
  `db/interfaces/documents.py` and `db/sqlite/documents.py`.
- The blob store takes `blob_id: bytes` while `items.image_key` is SHA-256 **hex**. The
  application converts at the boundary; `pylib` keeps its byte-oriented API.
- §6.3's sketch of the items envelope omits `total`. §6.0 says every collection has one,
  and the photo pass depends on it, so it is present.
