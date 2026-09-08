# Boxes Boxes Boxes: Specification

A personal tool for recording which numbered box a thing ended up in, searchable from a
laptop or a phone.

This document is the contract. It is deliberately precise about the HTTP API and the data
model, and deliberately loose about everything else.

---

## 1. Problem

Physical possessions get stored in numbered boxes. Months later, the question is always
"which box is the drill in?", and the answer currently requires opening boxes.

The tool answers that question in one search field.

**Two contexts, equally important, used for different things.**

*Laptop, sitting down:* create boxes, enter their contents, curate tags. This is where the
database gets built, and where the tool will be used most heavily at the start, the first
job is cataloguing an apartment's worth of cupboards and drawers.

*Phone, one hand, standing in front of a cupboard:* single items, both directions. Looking
one up by typing a word and seeing the item, its box number and where that box is, and
filing one: a single object that needs a home, recorded and photographed on the spot.
This is the flow that continues indefinitely once the initial cataloguing is done.

Neither is the primary target and neither is an adaptation of the other. Each is tailored
to what it is good at.

---

## 2. Repositories

Three repositories. One of them does not exist yet and must be created as the first task.

| Repository | Status | Role |
|---|---|---|
| **boxes-boxes-boxes** | to create | The application. Everything in this spec unless stated otherwise. |
| **pylib** | **does not exist yet, create it** | Reusable components, shared across personal projects. Initially just the blob store. |
| **no-more-paper-2** | exists | A *separate, unfinished project*. Read-only reference material. |

> `pylib` is a placeholder name. Any name works; it appears in this spec only in
> §2.2 and §2.3 and in import statements.

### 2.1 `no-more-paper-2` is read-only

**It is not touched, not forked, and not modified.** It is an unfinished project the author
intends to return to, and it stays exactly as it is.

It happens to contain a working sketch of a similar shape: FastAPI, Pydantic, SQLAlchemy
Core over SQLite, an abstract database class, a blob store. It is worth reading for
patterns and conventions (§12). Read it for inspiration; write nothing to it.

A consequence worth stating plainly: extracting the blob store means **copying the code out,
not moving it.** `no-more-paper-2` keeps its own copy and continues to work untouched. The
duplication is intentional and harmless because that repository is frozen; if and when its
author returns to it, switching it over to depend on `pylib` is a decision for that day.

### 2.2 Task: create the reusable components repository

The blob store is generic byte storage that knows nothing about boxes, items, or images,
or, for that matter, about content addressing. That is precisely why it should not live
inside an inventory application.

**Create a new repository** with this layout:

```
pylib/
  pyproject.toml
  src/pylib/__init__.py
  src/pylib/blobstore/__init__.py        # empty; names are imported from the modules below
  src/pylib/blobstore/blob_store.py      # BlobStore ABC + BlobNotFoundError
  src/pylib/blobstore/filesystem.py      # FileSystemBlobStore
  tests/test_filesystem_blob_store.py
```

Copy `blob/blob_store.py`, `blob/filesystem_blob_store.py`, and
`tests/test_filesystem_blob_store.py` from `no-more-paper-2` as the starting point. They
are already generic.

**One behavioural change is required: `put` must write atomically.** The existing
implementation calls `path.write_bytes(blob)` directly, so a concurrent reader, or a
backup process copying the directory, can observe a half-written file. Instead: write to a
temporary file, `fsync` it, then `os.replace` onto the final path, which is atomic on
POSIX. The temporary file must be on the same filesystem as the destination, so
`FileSystemBlobStore` takes an optional `tmp_dir` (defaulting to the store root) that the
application points at `/data/tmp/` to keep the blob tree clean (§7.6).

**Beyond that, the store is deliberately dumb.** `put` writes the bytes it is given at the
id it is given. It does not hash, does not verify that the id relates to the content, and
does not refuse an id that already exists, writing an existing id simply overwrites it,
atomically.

That the ids *happen* to be content hashes is a policy of the calling application (§4), and
the store has no knowledge of it. A store that tried to verify content against id would in
fact be wrong about most of what it holds: the blob id is the SHA-256 of the uploaded
`original`, while the derived `full` and `thumb` variants live under that same id with
different suffixes. Their bytes are not the hash of their key, and never will be.

Overwriting is likewise not a theoretical allowance, `regenerate_images` (§4) rewrites the
derived variants in place under an unchanged key. A write-once store would make that
impossible.

The one guarantee the store does make beyond "write bytes" is **atomicity**, and that is
justified independently of immutability: it is what stops a backup, or any concurrent
reader, from observing a half-written file. That benefits every caller, so it belongs in
the store. Immutability does not, and is not asserted here.

`pyproject.toml`:

```toml
[project]
name = "pylib"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = []

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = { "" = "src" }

[tool.setuptools.packages.find]
where = ["src"]
```

**One distribution package, submodules per component.** Adding component number two means a
new subpackage, not a new build and a new dependency entry. Split into separate
distributions only if a component ever grows heavy third-party dependencies that unrelated
consumers shouldn't inherit.

`pylib` takes **no dependency on this application**, and its API must not mention boxes,
items, or inventory concepts.

### 2.3 Consuming `pylib`: git source, no PyPI

Nothing is published to PyPI. `uv` consumes `pylib` directly from git, pinned to a tag.

**Primary configuration** in `boxes-boxes-boxes/pyproject.toml`:

```toml
[project]
dependencies = [
    "fastapi[standard]>=0.125.0",
    "sqlalchemy>=2.0.45",
    "alembic>=1.14",        # migrations (§7.5)
    "pillow>=11",           # image variants (§4)
    "pillow-heif>=0.21",    # HEIC decoding, iPhones shoot it by default
    "pylib",
]

[tool.uv.sources]
pylib = { git = "https://github.com/<user>/pylib", tag = "v0.1.0" }
```

`uv.lock` records both the tag and the resolved commit hash, so builds are reproducible
even if a tag is later moved. Releasing a new version of `pylib` is: commit, `git tag
v0.2.0`, push, then bump the tag here and run `uv lock`.

**While actively iterating on `pylib`**, switch temporarily to an editable path source so
changes are picked up without a tag-and-push cycle:

```toml
[tool.uv.sources]
pylib = { path = "../pylib", editable = true }
```

Switch back and re-lock before building an image.

#### Options considered

| Mechanism | Docker build | Versioning | Notes |
|---|---|---|---|
| **git + tag, remote URL** ✅ | works with no extra setup | real tags, locked to a commit | Chosen. `pylib` is a **public** GitHub repository, so the Docker build clones it without credentials, no tokens, no BuildKit secrets. |
| git + tag, `file://` URL | needs the repo inside the build context or a bind mount | real tags | **Verified working**: `{ git = "file:///home/brasse/github/pylib", tag = "v0.1.0" }` resolves, installs and locks correctly. Good offline fallback; awkward in Docker. |
| Path dependency, `../pylib` | ✗ parent directory is outside the build context | none | Best development loop, unusable for image builds on its own. |
| Git submodule at `vendor/pylib` + path source | works, in context | pinned commit | Viable, but submodule ergonomics for one dependency isn't worth it. |
| Locally built wheel committed to `vendor/` | works, fully offline | version in filename | Most robust and least elegant. Fall back to this only if git access from the build ever becomes a problem. |

---

## 3. Decisions already made

These are settled. Rationale is recorded so it doesn't have to be re-derived later.

| Area | Decision | Why |
|---|---|---|
| Users | One user, username + password, credentials in the `users` table | Only one person uses this, but storing credentials like every other piece of user data keeps multi-user a login-form change rather than a migration. |
| Sessions | Signed `HttpOnly` cookie | Log in once on the phone, stay logged in. Has a real logout. |
| Ownership | `user_id` on every table from day one | Retrofitting ownership later is a migration plus every query; carrying it now is one column. |
| Boxes | Explicit entities, created before use | Boxes are rare and long-lived; items are frequent. Picking from a list beats typing a number and hoping. |
| Box numbers | Typed by the user, server suggests the next free one | Fast for new boxes, still works for boxes already labelled with a marker. |
| Item location | Exactly one box, always | Simplest thing that answers the primary question. |
| Search | One text field over item titles and tags | Matches actual expected usage; the API contract is deliberately broader (see §6.3). |
| Backend | FastAPI + Pydantic + SQLAlchemy Core | Familiar, boring, sufficient. |
| Database | SQLite, not Postgres | One user, one process, one machine. Postgres would add a container, a connection string and a backup story to answer questions this app doesn't have. See §7.1. |
| Portability | Schema defined once, dialect-neutrally; SQLite specifics quarantined behind an ABC | Swapping databases later should be a new implementation class plus a copy script, not a rewrite. See §7.4. |
| Images | Original retained; `full` and `thumb` derived from it and regenerable | The chosen sizes and encodings will turn out slightly wrong; keeping the original makes that revisable rather than permanent (§4). |
| Blob storage | External `BlobStore` from `pylib`, a dumb byte store, no hashing or verification | Reusable component; belongs in its own repository (§2.2). Content addressing is the application's policy, not the store's. |
| Frontend | React + TypeScript + Vite | Most reliable to generate, explicit to review, types generated from OpenAPI. |
| Deployment | One Docker container, one volume, behind Caddy over HTTPS; reached on the LAN or via Tailscale | The app speaks plain HTTP and knows nothing of TLS, Caddy or Tailscale, all three are transport (§9). |
| Rate limiting | None in the application | Reachable only from LAN and tailnet. If ever wanted, it belongs in Caddy and needs no application code (§9). |

---

## 4. Domain model

### Box

A physical container with a number written on it.

| Field | Type | Notes |
|---|---|---|
| `id` | opaque string | Public identifier, used in URLs. Base62, 16 chars. |
| `number` | integer | User-facing, written on the physical box. Unique per user. `>= 1`. |
| `name` | string, optional | e.g. "Winter clothes". Max 200 chars. |
| `description` | string, optional | Free text. Max 2000 chars. |
| `location` | string, optional | Free text, e.g. "Basement", "Bedroom closet". Max 200 chars. |
| `item_count` | integer | Derived, read-only. |
| `created_at` | timestamp | UTC, RFC 3339. |

`location` is free text rather than a fixed list of rooms, with client-side autocomplete
from values already used (§6.2). This keeps "Basement" consistent without imposing a
taxonomy that will inevitably be wrong.

### Item

A thing inside a box.

| Field | Type | Notes |
|---|---|---|
| `id` | opaque string | Public identifier. Base62, 16 chars. |
| `title` | string, required | Max 200 chars. Non-empty after trimming. |
| `description` | string, optional | Free text. Max 2000 chars. |
| `tags` | list of strings | Normalised: trimmed, lowercased, deduplicated. Max 20 tags, each max 32 chars, `[a-z0-9-]`. |
| `box` | embedded box summary | `{id, number, name, location}`. Always present. |
| `image_key` | string or `null` | SHA-256 of the uploaded original, or `null`. Doubles as a cache key. |
| `image_original_type` | string or `null` | MIME type of the uploaded original, e.g. `image/heic`. Needed to serve `?variant=original` with a correct `Content-Type`; the derived variants are always JPEG. |
| `created_at` | timestamp | UTC, RFC 3339. |
| `updated_at` | timestamp | UTC, RFC 3339. |

An item is **always** in exactly one box. Moving it means changing `box_id`; removing it
permanently means deleting it.

### Image

At most one image per item, stored through the external `BlobStore` dependency (§2) in
namespace `items`. **Three variants** are written per image:

| Variant | Contents | Mutable? |
|---|---|---|
| `original` | The uploaded file, byte for byte, untouched | **No**, its key is its hash |
| `full` | Longest edge 2048px, JPEG, for the detail view | Yes, regenerable |
| `thumb` | Longest edge 320px, JPEG, for list views | Yes, regenerable |

**The original is retained deliberately, as the source of truth.** The exact dimensions,
encoding and processing chosen for `full` and `thumb` are guesses that will turn out to be
slightly wrong, too small, too compressed, wrong sharpening. Keeping the original means
those are revisable by re-deriving from it, rather than permanent:

```
python -m boxes3.regenerate_images [--variant full|thumb] [--dry-run]
```

Iterates every item with an image, reads its `original`, re-derives the display variants
with current settings, and writes them back **under the same key**. This is precisely the
case that requires the blob store to permit overwriting an existing id (§2.2), that
permission is not merely harmless here, it is load-bearing.

**Only `original` is immutable**, and only because its key is the hash of its own bytes.
`full` and `thumb` are derived artifacts that are *expected* to change, which is the whole
point of keeping the original, and which is why they are cached differently (§6.4).

Regeneration is a **development-time operation**. Once the chosen sizes and encodings have
settled, it is not expected to run again, so nothing in the application is built to
propagate it automatically.

Accepted input: JPEG, PNG, WebP, HEIC. Max 20 MB. **Uploads are not downscaled by the
client**, the file arrives exactly as the camera produced it, HEIC included (§8). For the
derived variants, EXIF orientation is applied and remaining EXIF metadata is stripped; the
`original` keeps its metadata intact, being an archive copy.

Image processing (decode, resize, re-encode) belongs to this application, not to the blob
store, the blob store stores bytes and knows nothing about images. Decoding HEIC requires
`pillow-heif` alongside Pillow.

Do not run `regenerate_images` while a backup is in progress, for the same reason as `gc`
(§7.6).

**The blob id is the SHA-256 of the uploaded original**, and `items.image_key` holds that
hash. All three variants live under that one key. `items.image_original_type` records the
original's MIME type, since the stored bytes alone don't say how to serve them; `full` and
`thumb` are always JPEG and need no such column.

**Content addressing is an application policy, not a property of the blob store.** `pylib`'s
store writes whatever bytes it is handed at whatever id it is handed, and will overwrite
without complaint (§2.2). The guarantees the backup argument in §7.6 depends on come from
these rules being followed here:

- The `original` variant, once written under a key, is never rewritten. It cannot
  meaningfully differ: the key is the hash of those exact bytes.
- Replacing an item's photo computes a **new** hash from the new upload, writes under that
  new key, and repoints the row.
- Deleting an item does **not** delete its blobs. They become orphans, reclaimed later by a
  manual `gc` command (§7.6).
- Identical uploads deduplicate naturally, since identical bytes hash identically.
- `full` and `thumb` **are** rewritten, by `regenerate_images`. This is safe because
  nothing references their content, only the key, and writes are atomic.

`FileSystemBlobStore` already takes `blob_id: bytes` and shards on its leading bytes, which
suits a content hash well, but that is a convenience, not an assumption the store makes.

**Write ordering is mandatory: the blob is written and durable *before* the database row
referencing it is committed.** The reverse order permits a committed row pointing at a
file that does not yet exist.

---

## 5. Authentication

One user today, stored as though there could be many.

**Credentials live in the `users` table, not in configuration.** Every other table already
carries `user_id` (§3) specifically so that multi-user is not a migration later; putting the
password somewhere else would make it the one piece of user data that doesn't follow the
pattern. `users` holds a unique `username` and a scrypt `password_hash`, `hashlib.scrypt`
from the standard library, no extra dependency. Plaintext is never stored and never written
to a config file.

`POST /api/auth/login` verifies username and password and sets a session cookie:

| Attribute | Value |
|---|---|
| Name | `session` |
| Content | Signed token containing the **username** and an expiry, not the internal user id (§6.0). |
| `HttpOnly` | always |
| `SameSite` | `Lax` |
| `Secure` | configurable; **default `false`** |
| `Max-Age` | 30 days, refreshed on use |

> **The default is `false` deliberately, and this matters for a public repository.** A
> `Secure` cookie is never sent over `http://`, so a fresh clone run at
> `http://localhost:8000` would appear to log in and then instantly not be logged in, with
> no error explaining why. Defaulting to `false` makes cloning and running work.
>
> Deployments behind TLS set `session_cookie_secure = true`; the reference deployment (§9)
> does.

Every endpoint under `/api` requires a valid session and returns `401` without one, with
exactly two exceptions:

- `POST /api/auth/login`, no session yet, by definition.
- `POST /api/admin/backup`, authenticated by a shared token instead, because the caller is
  a backup script rather than a browser (§6.6).

### Setting a password

```
python -m boxes3.set_password <username> [--password <pw>]
```

Creates the user if absent, updates the hash if present, and prompts for the password
interactively unless `--password` is given, so it stays out of shell history by default.

**There is no automatic password generation and nothing is printed to stdout.** A fresh
installation starts with no users, and the app logs a clear instruction to run this command
on startup when the `users` table is empty. Logging in is impossible until it has been run,
which is the intended behaviour rather than a dead end.

**Implementation shape.** A single FastAPI dependency:

```python
async def get_current_user(request: Request) -> User: ...
```

Endpoints declare `user: Annotated[User, Depends(get_current_user)]` and never reason
about auth again. Today it resolves the single configured user. Replacing it with real
accounts later changes this one function; no endpoint signature changes.

---

## 6. HTTP API

Base path `/api`. All request and response bodies are JSON unless stated otherwise. All
models are Pydantic; the OpenAPI schema is the source of truth for the TypeScript client.

### 6.0 Conventions

#### Identifiers

**Internal integer primary keys never cross the API boundary.** Every row has two
identifiers, and they have separate jobs:

| | Internal | External |
|---|---|---|
| Column | `id`, autoincrement integer | `public_id`, base62, 16 chars, from `secrets.choice` |
| Used by | primary keys, foreign keys, joins | every URL, request body and response |
| Visible to clients | **never** | always |

The internal key is compact, gives fast joins and good index locality. The external id is
what the outside world sees, because it is unguessable and not *enumerable*. Nobody can
walk `/items/1`, `/items/2`, and it doesn't leak how many rows exist or in what order
they were created.

Consequences, all of which the implementation must honour:

- API models expose the external id **as `id`**. The internal `id` column is never
  serialised, and `public_id` never appears as a field name in JSON.
- `box_id` in a request body is a box's *external* id. Resolving it to an internal key
  happens in the database layer.
- **Users are the exception, and needed no opaque id at all:** the external identifier is
  the `username`. It is already unique and already typed at a login screen, so a third
  identifier would serve nothing. `user_id` therefore appears nowhere in any response,
  including `GET /api/auth/me`, and including the signed session cookie.
- Error messages must not embed internal keys either.
- Pagination cursors are opaque and their contents are not part of the contract; what they
  encode internally is an implementation detail.

Boxes carry a third, user-facing identifier, `number`, written on the physical box. URLs
still use the external id rather than the number, because `number` is editable (§6.2) and a
URL that changes when you renumber a box is a URL that breaks bookmarks.

#### Errors

Errors use a single consistent shape:

```json
{ "error": { "code": "box_number_taken", "message": "Box number 23 already exists." } }
```

`code` is a stable machine-readable string; `message` is for humans and may change.

| Status | Meaning |
|---|---|
| `400` | Malformed request. |
| `401` | No valid session. |
| `404` | No such resource. |
| `409` | Conflict, duplicate box number, or a backup already running. |
| `413` | Uploaded image too large. |
| `415` | Unsupported image type. |
| `422` | Validation failure. |

**Every error response uses this shape, with no exceptions.** FastAPI does not do this by
default: `HTTPException` emits `{"detail": "..."}` and request validation emits
`{"detail": [ ... ]}`, so without intervention the API would speak three different error
dialects and every frontend error path would have to sniff which one it received. Register
exception handlers for `HTTPException`, `RequestValidationError` and unhandled exceptions
that translate all of them into the envelope above.

A body on a 4xx response is entirely correct HTTP: RFC 9110 says a client-error response
*should* carry a representation explaining the problem. Only `1xx`, `204` and `304` are
required to be bodyless, which is why `POST /api/auth/logout` and the `DELETE` endpoints
return `204` with nothing.

Two practical notes:

- **`401` deliberately omits `WWW-Authenticate`.** The header is nominally required, but
  sending `Basic` makes browsers open their own native credentials dialog on top of the
  application's login screen. Cookie-authenticated APIs routinely omit it; so does this one.
- **A `413` body may never reach the client.** If the server rejects an oversized upload
  before consuming the request, the client can observe a connection reset rather than JSON.
  With 3 to 5 MB originals (§4) this is realistic, so the frontend must treat a failed upload
  with no parseable response as "too large" rather than failing silently.

**Collections** always return an envelope, never a bare array:

```json
{ "items": [ ... ], "total": 137, "next_cursor": "eyJvIjoxMDB9" }
```

`next_cursor` is `null` on the last page. `total` is the number of matches across all
pages, not just the current one, the photo pass needs it to show "9 items need a photo"
and "3 / 12" (§8), and counts of that kind are otherwise unobtainable.

The envelope is not optional. A bare array leaves nowhere to add facets or ranking metadata
later without breaking clients.

**Pagination** is cursor-based. `limit` defaults to 50, max 200. Cursors are opaque;
clients pass back exactly what they received.

**Two endpoints deliberately return unpaginated lists**: `GET /api/tags` and
`GET /api/boxes/locations`. Both are naturally bounded (tens of entries) and exist to feed
autocomplete, where pagination would be meaningless.

### 6.1 Auth

```
POST   /api/auth/login  { "username": "...", "password": "..." }
                                                  → 204 + Set-Cookie   | 401
POST   /api/auth/logout                           → 204
GET    /api/auth/me     → { "username": "brasse" }                     | 401
```

`GET /api/auth/me` exists so the frontend can decide on load whether to show the login
screen, without guessing from a failed data request.

**No rate limiting.** Deliberately out of scope, see §9.

### 6.2 Boxes

```
POST   /api/boxes                → 201 Box    | 409 box_number_taken
GET    /api/boxes                → { "boxes": [Box], "total": n, "next_cursor": ... }
GET    /api/boxes/next-number    → { "number": 24 }
GET    /api/boxes/locations      → { "locations": ["Basement", "Bedroom"] }
GET    /api/boxes/{box_id}       → Box        | 404
PATCH  /api/boxes/{box_id}       → Box        | 404 | 409
DELETE /api/boxes/{box_id}       → 204        | 404 | 409 box_not_empty
```

**A box's contents are `GET /api/items?box=<id>`**, not a dedicated sub-resource. An earlier
draft had `GET /api/boxes/{box_id}/items` as well; it was removed once the `box` filter
existed for the photo pass. Two ways to ask the same question means two pagination
implementations to keep consistent, for no gain.

`POST /api/boxes` body: `{ number, name?, description?, location? }`.

`PATCH /api/boxes/{box_id}` accepts any subset of `{ number, name, description,
location }`. Omitted fields are unchanged; explicit `null` clears an optional field.

`GET /api/boxes` accepts `q` (matches box number, name, and location), `limit`, `cursor`.
Default order is by `number` ascending.

`GET /api/boxes/next-number` returns the lowest unused positive integer, used to pre-fill
the create form. It is a suggestion, not a reservation: two concurrent creates could
collide, and the loser gets `409`. Acceptable for a single-user tool.

`DELETE` on a box holding items returns `409`. Pass `?force=true` to delete the box and
all its items. The UI must confirm, showing the item count.

`GET /api/boxes/locations` returns distinct non-empty locations already in use, for
autocomplete.

### 6.3 Items

```
POST   /api/items           → 201 Item   | 404 box_not_found
GET    /api/items           → { "items": [Item], "next_cursor": ... }
GET    /api/items/{item_id} → Item       | 404
PATCH  /api/items/{item_id} → Item       | 404
DELETE /api/items/{item_id} → 204        | 404
```

`POST /api/items` body: `{ title, box_id, tags?, description? }`, where `box_id` is a
box's **public** id, the same opaque string returned by `GET /api/boxes` (§6.0).

`PATCH /api/items/{item_id}` accepts any subset of `{ title, description, tags, box_id }`.
Changing `box_id` is how an item is moved.

**Search: `GET /api/items`**

| Parameter | Type | Meaning |
|---|---|---|
| `q` | string, optional | Free-text query. **Opaque.** |
| `tag` | string, repeatable | Item must have all given tags. |
| `box` | box id, optional | Restrict to one box. |
| `has_image` | boolean, optional | Filter on whether an image is attached. Drives the photo pass (§8). |
| `limit` | integer | Default 50, max 200. |
| `cursor` | string | Opaque pagination cursor. |

Three rules keep this extensible, and they are the point of this section:

1. **`q` is defined semantically, not syntactically.** It is "a free-text query; the server
   decides what it matches." Today it matches item titles and tags. It may later match
   descriptions, box names, or locations. Clients never construct query syntax, so
   broadening it is not a breaking change.

2. **Results are returned in server-defined order and clients must not re-sort.** Today
   that order is `updated_at` descending. The day it becomes relevance ranking, the app
   improves for free, but only if the frontend didn't impose its own sort.

3. **Structured filters stay separate from `q`.** Adding `location=` or `created_before=`
   later is then purely additive.

**First implementation:** case-insensitive `LIKE` across item title and tags. No stemming,
no ranking. This is intentionally the simple thing.

**Upgrade path (not in scope now):** a SQLite FTS5 virtual table kept in sync by triggers,
giving word matching and relevance ranking. Because the database sits behind an abstract
base class (§7), this changes one method in one class and touches no API and no frontend
code.

Note that "what is in box 12" is *not* a search concern, it is `GET /api/items?box=<id>`
with no `q`, which is an exact structured filter and always correct regardless of how `q`
is implemented.

### 6.4 Images

```
PUT    /api/items/{item_id}/image  multipart/form-data, field "file"
                                   → 200 Item | 404 | 413 | 415
DELETE /api/items/{item_id}/image  → 204 | 404
GET    /api/items/{item_id}/image  ?variant=thumb|full|original  (default: full)
                                   → image/jpeg, or the original's own type | 404
```

`PUT` replaces the item's image by writing a **new** blob and repointing `image_key`; the
previous blob is orphaned rather than overwritten (§4). `DELETE` clears `image_key` and
leaves the blob in place. Neither operation ever removes bytes from the store, that is
`gc`'s job (§7.6).

#### Caching

Browsers cache by URL, and `/api/items/{item_id}/image?variant=thumb` does not change when
the photo behind it does. Without help, replacing a photo leaves the old one on screen
indefinitely.

**Replacing a photo is handled by the URL.** The frontend appends the item's `image_key`:

```
/api/items/{item_id}/image?variant=thumb&v=<image_key>
```

The server **ignores `v` entirely**: it exists only to make the URL differ, which is what
makes the browser's cache entry differ. Upload a new photo, the key changes, the URL
changes, the new image appears immediately.

**Regeneration is handled by the cache lifetime instead**, because the two variants have
genuinely different mutability:

| Variant | `Cache-Control` | Why |
|---|---|---|
| `original` | `private, max-age=31536000, immutable` | Its key is the hash of its own bytes. These can never differ. |
| `full`, `thumb` | `private, max-age=86400` | Derived, and rewritten by `regenerate_images` under an unchanged key. |

A one-day lifetime on the derived variants means regenerated images appear everywhere
within a day, on their own, on every device. Nothing needs to know that regeneration
happened.

**This is deliberately not automatic**, and the reasoning is worth keeping. Making
regeneration propagate instantly requires a generation counter threaded through the config,
the command, the item model, and every image URL. Regeneration is a development-time
operation, once the sizes and encodings settle it never runs again, so that machinery
would be carried forever to serve an event that stops happening.

The alternative to a short lifetime is `immutable` plus manually clearing browser caches,
and that is worse than it sounds: desktop is a hard reload, but **iOS Safari has no per-site
cache clear at all**. The only option is Settings → Safari → Clear History and Website Data,
which wipes every site, and a PWA install has to be deleted and re-added. One day of
staleness is a much better trade than that.

If a day is too long to wait during active development, a hard reload (`Ctrl`/`Cmd` +
`Shift` + `R`) still works on the machine doing the work.

### 6.5 Tags

```
GET /api/tags  → { "tags": [ { "tag": "tools", "count": 12 } ] }
```

Ordered by count descending. Used for tag autocomplete when adding an item, which is what
keeps tags from fragmenting into "tool", "tools", and "Tools".

### 6.6 Admin

```
POST /api/admin/backup  → 200 { "path", "bytes", "created_at" } | 409 backup_in_progress
```

Blocks until a consistent database snapshot has been written and fsynced. Authenticated by
`Authorization: Bearer <backup_token>`, **not** by session cookie, since the caller is a
backup script. Disabled entirely when no token is configured. Full design in §7.6.

> **On "bearer token".** Nothing standardised is being relied on here. `Authorization:
> Bearer <token>` is an OAuth 2.0 convention (RFC 6750), but mechanically it is a string in
> a header compared against a secret. `X-Backup-Token: …` would work identically. The
> convention is kept for one practical reason: logging and proxy tooling commonly redacts
> `Authorization` by default, while a custom header goes straight into the logs.

---

## 7. Storage

SQLite via SQLAlchemy Core.

### 7.1 Why SQLite and not Postgres

Postgres exists to solve concurrent writers, network access from multiple hosts, and rich
typing. This application has **one user, one process, one machine**, so none of those
questions are being asked. What Postgres would actually add is a second container, a
compose file, a connection string, startup ordering, and a `pg_dump` backup story: a
permanent operational tax on a tool whose main virtue is sitting there working unattended.

SQLite instead means the database is a file, backup is copying a directory, and the driver
ships with Python. The one-container, one-volume deployment in §9 depends on this.

**Where Postgres would genuinely win is full-text search**: `tsvector` with GIN indexing,
plus `pg_trgm` for typo-tolerant matching, is more capable than FTS5. But FTS5 provides
porter stemming, BM25 ranking, prefix queries and a trigram tokenizer, which is far beyond
what a few thousand household items require. Hitting that ceiling is the signal to
reconsider; §7.4 keeps reconsidering cheap.

### 7.2 Required connection settings

Applied to every connection, via a SQLAlchemy `connect` event listener:

| Pragma | Value | Why |
|---|---|---|
| `foreign_keys` | `ON` | **SQLite disables foreign key enforcement by default.** Without this the `ON DELETE RESTRICT` below silently does nothing and boxes can be deleted out from under their items. |
| `journal_mode` | `WAL` | Readers don't block the writer. Set once per database, persists. |
| `synchronous` | `NORMAL` | Correct pairing with WAL; safe against process crash. |
| `busy_timeout` | `5000` | Wait rather than immediately raising "database is locked". |

Timestamps are stored as RFC 3339 UTC strings, since SQLite has no native datetime type.

### 7.3 Schema

```
users       id                 PK
            username           UNIQUE, NOT NULL
            password_hash      NOT NULL
            created_at         NOT NULL

boxes       id                 PK
            public_id          UNIQUE, NOT NULL
            user_id            FK → users.id, NOT NULL
            number             NOT NULL, CHECK (number >= 1)
            name               NULL
            description        NULL
            location           NULL
            created_at         NOT NULL
            UNIQUE (user_id, number)

items       id                 PK
            public_id          UNIQUE, NOT NULL
            user_id            FK → users.id, NOT NULL
            box_id             FK → boxes.id, NOT NULL, ON DELETE RESTRICT
            title              NOT NULL, CHECK (length(trim(title)) > 0)
            description        NULL
            image_key          NULL    -- SHA-256 hex of the uploaded original
            image_original_type NULL   -- MIME type of that original, e.g. image/heic
            created_at         NOT NULL
            updated_at         NOT NULL

item_tags   item_id            FK → items.id
            tag
            PRIMARY KEY (item_id, tag)
```

Additional indexes (beyond those implied by the keys above): `items.box_id`,
`items.user_id`, `item_tags.tag`.

#### On the constraints

**`public_id` is `UNIQUE`, not merely indexed.** An index makes lookups fast but permits
duplicates; since every API request resolves a row by its public id, a duplicate would make
one of the two permanently unreachable.

**`UNIQUE (user_id, number)` is composite on purpose.** It means the *pair* is unique, so
two users may each own a box 7 while one user may not own two. Note that widening a `UNIQUE`
constraint *weakens* it: `UNIQUE (id, user_id, number)` would enforce nothing at all, since
`id` is already unique and every combination containing it is unique by construction. One
constraint per rule, not one big one.

**`image_key` is deliberately not unique.** Identical uploads hash identically (§4), so two
items legitimately share a key, for instance photographing six identical storage bins
once and attaching that photo to each. Deduplication is a *consequence* of content
addressing rather than a goal; this note exists so that nobody later "tidies up" by adding
a `UNIQUE` constraint that would reject the second item for no discoverable reason. Its one
real consequence is that `gc` must reclaim only blobs referenced by **no** row (§7.6).

**`item_tags` stores tag strings directly rather than referencing a `tags` table.** A
normalised design earns its keep when the entity has attributes beyond its name: a colour,
a description, a parent. A tag here *is* its string, so the extra table would hold an id and
the string it replaced while every query gained a join. Storage is not a factor: 5,000 items
at three tags each is roughly 150 KB. Even a global rename stays one statement
(`UPDATE item_tags SET tag = 'tools' WHERE tag = 'tool'`). **Revisit only if tags gain
attributes of their own.**

Forced box deletion (`?force=true`, §6.2) removes the items explicitly in the same
transaction, since `ON DELETE RESTRICT` deliberately prevents cascading.

Deleting an item does **not** delete its blobs, see §7.6.

Public ids are generated with `secrets.choice` over a base62 alphabet, **not**
`random.choice`, which is not cryptographically secure and would be a poor choice for
values that appear in URLs.

### 7.4 Keeping the database swappable

SQLite is right for now, but changing it later must be a bounded job: a new implementation
class and a data copy, not a rewrite. Three rules achieve that, and they cost nothing today:

**1. The schema is defined once, dialect-neutrally.** One set of SQLAlchemy Core `Table`
objects against a shared `MetaData`, using portable types (`Integer`, `Text`, `String`,
`Boolean`). No raw DDL, no SQLite-only column types. Another backend can then run
`metadata.create_all()` against the identical definitions. This is the load-bearing rule.

**2. Dialect-specific SQL stays inside the implementation class.** An `InventoryDatabase`
abstract base class defines the storage interface in domain terms, raising domain
exceptions (`BoxNotFoundError`, `BoxNumberTakenError`) rather than leaking driver errors.
Constructs like `sqlalchemy.dialects.sqlite.insert` for upserts are fine, *inside*
`SqliteInventoryDatabase`, never in a router or a service.

**3. Search is the known exception.** FTS5 is SQLite-only, so another backend would
reimplement that one method against its own engine. This is the correct amount of coupling:
contained, and identified in advance rather than discovered late.

Given those, migrating is a short script that reads each table through one engine and bulk
inserts through the other. The shared `MetaData` means both ends already agree on the
shape.

### 7.5 Migrations

The schema will change: milestone 2 adds a field (§11). Use Alembic from the start; it is
the standard companion to SQLAlchemy and works against both SQLite and Postgres. SQLite's
`ALTER TABLE` is limited, so Alembic's *batch mode* is required for anything beyond adding
a column.

**Alembic owns schema creation and evolution**, including on a fresh database: first run
applies migrations rather than calling `create_all()`. `metadata.create_all()` is used only
in tests and in the hypothetical database-port script of §7.4, where no migration history is
wanted. Having both paths build production schemas is how they drift.

### 7.6 Backup

**Requirement.** An external, already-existing backup system runs daily. It can invoke a
pre-backup hook, and then copies files. All intelligence must live in this application; the
external side must be nothing more than *call a URL, then copy a directory*.

#### Why a plain copy is not enough on its own

A live SQLite database in WAL mode is three files: `.db`, `.db-wal`, `.db-shm`. Copying
them while the application is writing can capture them at inconsistent moments or catch the
main file mid-checkpoint. It usually works, and occasionally produces a database that looks
fine until the day it is needed. That is designed out rather than tolerated.

#### The mechanism

```
POST /api/admin/backup    → 200 { "path": "...", "bytes": 483328,
                                  "created_at": "2026-09-04T02:00:03Z" }
                          → 409 backup_in_progress
```

The endpoint **blocks until the snapshot is complete and durable**, then returns. It:

1. Runs `VACUUM INTO '/data/tmp/inventory.db.tmp'`, producing a consistent, compacted
   single-file copy.
2. `fsync`s it, then `os.replace`s it to `/data/backup/inventory.db`, atomic, so a reader
   never observes a partial file.
3. Holds a lock for the duration; a concurrent call gets `409` rather than interleaving.

Snapshots take milliseconds at this data size, so blocking is not a concern.

**Authentication.** The endpoint is called by a script, not a browser, so it does not use
the session cookie. It requires `Authorization: Bearer <token>` matching `BACKUP_TOKEN`
from config. If `BACKUP_TOKEN` is unset, the endpoint is disabled entirely.

#### Backup procedure

```
0. BACKUP_TOKEN=$(python3 -c 'import tomllib; print(tomllib.load(open("/data/config.toml","rb"))["backup_token"])')
1. curl -fsS -X POST -H "Authorization: Bearer $BACKUP_TOKEN" \
        http://host:8000/api/admin/backup
2. copy /data  (excluding /data/tmp)
```

Step 1 must complete before step 2 begins, which is exactly what a pre-backup hook does.

#### Cross-store consistency

The database snapshot and the blob files are copied at different moments, with no
transaction spanning both. Three rules make that safe, and they are the reason for the
design in §4:

**1. Blobs are written before the rows that reference them.** So a committed row always
implies an already-durable blob. Without this, a snapshot could reference a blob whose
temporary file had not yet been renamed into place.

**2. Blobs are never deleted during normal operation.** Item deletion leaves them in place
(§4). This closes the subtler race: the snapshot is taken at T₀ but blobs are copied over
the following minutes, so deleting an item in that window would otherwise strand the
snapshot's reference. Copying blobs *before* snapshotting does not help; it merely inverts
the problem.

Note the requirement is **existence, not immutability**. All the snapshot needs is that the
blobs it references are still there when the copy runs. That distinction matters, because
the application does not in fact treat all blobs as immutable:

| Blob | Mutated? | Effect on a backup |
|---|---|---|
| `original` | Never, its key is the hash of its own bytes | None |
| `full`, `thumb` | Rewritten by `regenerate_images` (§4) | None: the blob still exists under the same key |

So `regenerate_images` joins `gc` on the list of things not to run mid-backup, but for a far
weaker reason. `gc` deletes, and a deletion mid-copy strands a reference. Regeneration only
rewrites, so the worst case is a backup containing a mix of old and new renderings, visibly
odd, entirely restorable, and fixed by re-running the command afterwards.

None of this is enforced by `pylib`, which will overwrite any id without complaint (§2.2).
It is a discipline of this application.

**3. The snapshot is taken before the copy starts**, enforced by the procedure above.

Between the snapshot and the copy the set of blob *keys* can therefore only grow. Everything
the snapshot references is still present. The only residue is orphan blobs, blobs the
snapshot doesn't reference, which restore harmlessly and waste a few kilobytes.

Temporary files are written to `/data/tmp/` rather than inside the blob tree: the same
filesystem, so `os.replace` stays atomic, but a backup that catches a write in progress
copies nothing stray from `/data/blobs/`.

#### Orphan collection

```
python -m boxes3.gc [--dry-run]
```

Deletes blobs not referenced by any row, *any* row, since two items may legitimately share
a key (§7.3). Run manually and rarely, and **not** while a backup is running. Orphans accumulate slowly, only from replaced or deleted images, so
this is maintenance, not housekeeping.

#### Restore

```
1. Copy the backup directory to /data on the new machine.
2. rm -f /data/inventory.db /data/inventory.db-wal /data/inventory.db-shm
3. cp /data/backup/inventory.db /data/inventory.db
4. Start the container.
```

A restored instance is immediately usable: login credentials travel inside the database
snapshot (§5), and `config.toml` in the same directory carries the session key, so existing
sessions survive too. **The restore procedure must be tested once, deliberately, before
relying on it.**

---

## 8. Frontend

React + TypeScript + Vite. **Two tailored layouts from one codebase**, neither of them the
"real" one, see "Layout across form factors" below for what each is for.

**API client types are generated from the OpenAPI schema** with
[`openapi-typescript`](https://github.com/openapi-ts/openapi-typescript), not hand-written.
It emits types only, no runtime and no client abstraction to learn, and is paired with a
thin hand-written `fetch` wrapper that sets `credentials: "include"` and unwraps the error
shape from §6.0. Generation runs as a `make` target against the running app's
`/openapi.json`, and the output is committed so a checkout type-checks without a backend.

This is what makes the API a real contract: a backend change that breaks the frontend fails
at compile time rather than at the cupboard.

### Screens

| Screen | Contents | Primary form factor |
|---|---|---|
| Login | Username field **and** password field, credentials live in the `users` table (§5), not a single shared password. Both marked up with the standard `autocomplete` hints so password managers work. | both |
| Search (home) | Search field focused on load; results show title, box number, box location, thumbnail. Tag filter chips. | both |
| Item detail | Full image, title, description, tags, box. Edit, move, delete. | both |
| Add item | Title, box picker (searchable), tags with autocomplete, photo taken inline. **The long-term everyday flow**, see below. | phone |
| **Pack a box** | Keyboard-driven repeat entry into one box. See below. | laptop |
| **Photo pass** | Queue of photo-less items in a box; shoot and auto-advance. See below. | phone |
| Box list | All boxes with number, name, location, item count. | both |
| Box detail | Box metadata plus its items. Edit, delete. | both |
| Add/edit box | Number (pre-filled from `next-number`), name, description, location with autocomplete. | laptop |

### Requirements

- Search input debounced ~250 ms; results must not reorder while typing.
- Photo capture uses `<input type="file" accept="image/*" capture="environment">` so the
  phone offers the camera directly.
- **No client-side downscaling.** The original file is uploaded untouched, because it is
  the archival source the display variants are re-derived from (§4). A phone photo is
  3-5 MB, so uploads run in the background with a visible progress indicator rather than
  blocking the flow, see the photo pass in this section.
- Every list is paginated via `next_cursor`.
- Session expiry (`401`) redirects to login, preserving the intended destination.
- Touch targets at least 44px **below the breakpoint**; above it, pointer-precision density
  is fine and preferable, since the laptop is doing keyboard-and-mouse work.
- Keyboard navigation is a first-class requirement above the breakpoint, not an
  accessibility afterthought: "pack a box" is unusable without it.

Styling is deliberately unspecified beyond "plain and legible". No component library is
required.

### Layout across form factors

The phone and the laptop are not the same UI at different widths, because they are used for
different jobs.

The dividing line is **one thing at a time versus many at once**, not reading versus
writing. Both devices do both.

**The phone handles single items, wherever you are standing.** Looking one up, "which box
is the drill in?", and equally adding one: a single object that needs a home, filed and
photographed on the spot. One hand free, no desk, camera present. It wants a search field, a
large readable answer, and an add-item flow that completes in one pass.

**The laptop handles volume and curation.** Sitting down with an open box, entering twenty
things into it, fixing tags across items, editing box descriptions. Keyboard work, badly
served by a thumb-oriented UI.

Note this does not map onto "first" and "later" either. Bulk entry dominates at the start
and then nearly stops; single-item phone entry begins immediately and continues
indefinitely.

This is **one codebase with one set of components**, not two applications. What changes is
layout and which screens are prominent.

#### Terminology

Frontend vocabulary used throughout this section, since it is not obvious from a backend
background:

| Term | Meaning |
|---|---|
| **viewport** | The browser window's content area. Not the physical screen. |
| **media query** | A CSS block applying only under a condition, typically a viewport width: `@media (min-width: 900px) { … }`. |
| **breakpoint** | The width value in such a query: the point where the layout switches arrangement. **Nothing to do with debugger breakpoints.** |
| **stack navigation** | One screen at a time; opening a detail replaces the list, Back returns. The phone pattern. |
| **master-detail** | A list and the selected item's detail side by side, both visible. The wide-screen pattern. |
| **debounce** | Wait for a pause in typing before firing a request, instead of one per keystroke. |
| **optimistic update** | Show the result immediately and reconcile when the server replies, rather than waiting for the round trip. |
| **mount / unmount** | React creating or destroying a component. An unmounted component loses its local state, which is why §"Presenting different UIs" prefers CSS over JavaScript branching. |
| **app shell** | The static frame of the app (layout, navigation, styles), cacheable separately from the data it displays. |

#### Breakpoint behaviour

A single breakpoint at **900px**:

```css
.results { display: block; }              /* applies always */

@media (min-width: 900px) {               /* applies from 900px up */
  .results { display: grid; grid-template-columns: 320px 1fr; }
}
```

Because it measures the **window** rather than the device, narrowing a window on the laptop
produces the phone layout, so the entire phone UI is developed and tested without a phone.
A tablet, or a half-width laptop window, lands on whichever side of 900 it falls.

Below it: **stack navigation**. One view at a time; tapping a result replaces the list with
the detail; Back returns.

At or above it: **master-detail, two panes**. Results stay in a left column while the
selected item's detail fills the right. Clicking through six search results costs six
clicks, not six round trips through a Back button. This is the single largest thing a wide
screen buys for this application.

```
DESKTOP (≥900px)                      PHONE (<900px)
┌──────────────────┬────────────────┐  ┌──────────────┐
│ ⌕ drill          │                │  │ ⌕ drill      │
├──────────────────┤  ┌──────────┐  │  ├──────────────┤
│▸ Drill      Box 7│  │ [ image ]│  │  │ Drill   Box 7│
│  Drill bits Box 7│  └──────────┘  │  │ Bits    Box 7│
│  Hammer     Box 7│                │  │ Hammer  Box 7│
│  Saw        Box 9│  Drill         │  │ Saw     Box 9│
│                  │  Box 7·Basement│  │              │
│                  │  #tools #power │  │  tap → detail│
│                  │  [Edit][Move]  │  │    replaces  │
└──────────────────┴────────────────┘  └──────────────┘
```

#### Routing

**The selected item lives in the URL, not in component state**: `/search?q=drill&item=<id>`.
The same URL then renders as two panes on a laptop and as the detail view on a phone, and
deep links, refresh, and the browser Back button behave correctly on both. Holding selection
in local state instead is the usual way this design goes wrong.

#### Presenting different UIs on the two devices

Some screens are genuinely single-device: "pack a box" is keyboard work, the photo pass
needs a camera. The rule for handling that:

**Navigation differs. Routing never does.**

Every screen keeps a URL that resolves on every device. Routes are not conditionally
registered. A bookmark, or a link sent to yourself, must not dead-end because it was opened
on the wrong device. What differs is what each device *offers*: the phone's navigation
doesn't surface "pack a box", the laptop's doesn't push the photo pass. Reaching either
directly still renders it, cramped but working. **Hide affordances, never hide capability.**

Within a screen, two mechanisms, and the choice between them matters:

| Mechanism | Use for | Why |
|---|---|---|
| CSS media queries | Same components, different arrangement | Nothing unmounts; component state survives a resize |
| `useMediaQuery('(min-width: 900px)')` | The component *tree* must genuinely differ, one pane vs two | Necessary, but remounts on crossing the breakpoint |

**Default to CSS and escalate to the hook only when the tree must change.** Crossing the
breakpoint with a JS branch unmounts and remounts the subtree, so a half-typed "pack a box"
entry would vanish when the window is dragged wider. Where a branch is unavoidable, the
state it wraps lives in the URL or above the branch, which the routing rule below already
requires for the master-detail selection.

Use `matchMedia` through a single small hook rather than tracking `window.innerWidth` on
resize; it fires only on threshold crossings instead of on every pixel.

#### Rules

- **Author CSS narrow-first**: base styles target the phone, and a single
  `@media (min-width: 900px)` block adds the two-pane layout. This is a maintainability
  convention, not a statement about priority: the base styles are the fallback, and
  widening a narrow layout works where cramming a wide one does not.
- **Build order is a separate question, and the answer is the laptop.** It is what gets
  used first and most heavily during initial cataloguing, so it is what should work first.
  The narrow base styles still get written; they just aren't what you look at on day one.
- **Nothing essential may depend on hover.** Touch devices have no hover state, so any
  action revealed by it is invisible on the primary device.
- Pointer-precision affordances (dense rows, right-click, drag) are permitted above the
  breakpoint only, and must have a touch-reachable equivalent below it.

#### Add item: the steady state

One object, one box, from wherever you are standing. Title, a searchable box picker, tags
with autocomplete, and a photo taken on the spot.

**This is the flow that outlives everything else in this section.** Bulk entry is
scaffolding: it runs hard for a few weekends while the apartment gets catalogued, and then
essentially never again. What continues indefinitely is finding one random object, deciding
which box it belongs in, and recording that from a phone, so this screen deserves the same
care as "pack a box", not less.

Consequently it must be complete on the phone in a single pass: the photo is taken inline
rather than deferred to the photo pass, since there is no bulk session to sweep up
afterwards. The box picker is searchable by number, name and location, because by then
there will be dozens of boxes and scrolling a list is not an answer.

#### "Pack a box": bulk entry

A laptop-oriented mode for adding many items to one box in sequence. **In milestone 1**,
because the database starts empty and populating it a full-page form at a time is the
difference between a productive weekend and an abandoned tool. It is deliberately
transitional: heavy use at the start, near-zero afterwards.

```
PACK BOX 7, Basement                       [Done]
┌────────────────────────────────────────────────┐
│ Title  [ hammer                    ]           │
│ Tags   [ tools × ] [ hand × ] [ + ]            │
│ Photo  [ drop or click ]  (optional)           │
│                                ⏎ Add & next    │
└────────────────────────────────────────────────┘
Added to box 7 this session:  6
  ✓ drill        ✓ drill bits
  ✓ saw          ✓ tape measure
  ✓ screwdriver  ✓ level
```

Behaviour:

- The box is chosen **once**, at the start, and stays fixed for the session.
- Enter submits and immediately refocuses the title field. The form does not navigate away
  and does not reset the box.
- Tags persist between entries by default, since consecutive items in one box usually
  share them, and are individually removable.
- Photos are optional and skippable; the flow must never block on one.
- A running list of what was added this session stays visible, each row undoable, so a
  typo doesn't require leaving the mode to fix.
- Optimistic insertion: the row appears immediately and is reconciled with the server
  response, so entry speed is never gated on the round trip.

No new API surface: this is repeated `POST /api/items` against a fixed `box_id`.

Photos are deliberately not the laptop's job. See below.

#### The photo pass: phone

**The problem this solves.** Bulk entry happens at a laptop, but the camera is on the
phone. If attaching a photo means taking one on the phone, waiting for a photo-library
sync, locating the file, and uploading it, then in practice **no item ever gets a photo**,
and the initial bulk import, which is most of the collection, is precisely the batch that
stays bare. That makes this milestone 1 work, not a refinement.

**Why there is no pairing step.** The obvious design is a QR code on the laptop that hands
the phone a capture session, so a photo can be bound to an item still being typed. That
machinery exists only because the item does not exist yet. Creating the item first, title
and tags, which is what keyboards are for, removes the problem: the item now has an id, so
the phone does not need to be handed anything. It simply asks which items lack a photo.

**The flow.** On the phone, per box:

```
PHONE, Box 7 · Basement
┌────────────────────────────┐
│  9 items need a photo      │
├────────────────────────────┤
│         hammer             │
│       #tools #hand         │
│                            │
│    ┌──────────────────┐    │
│    │  ◉  Take photo   │    │
│    └──────────────────┘    │
│                            │
│    [ Skip ]        3 / 12  │
└────────────────────────────┘
```

- Entered from a box, or from a "boxes with photo-less items" list.
- Backed by `GET /api/items?box=<id>&has_image=false`. The counters, "9 items need a
  photo", "3 / 12", come from the envelope's `total` (§6.0).
- Capture uses `<input type="file" capture="environment">`, so it needs no secure context
  and works over plain HTTP from any address (§9).
- Uploading advances to the next item automatically. **Skip** defers one without leaving
  the flow.
- Interruptible and resumable: the queue is derived from server state each time, not held
  in the session, so putting the phone down loses nothing.
- Upload is optimistic: the next item appears immediately while the previous one uploads
  in the background, so the flow is never gated on the network.

This is the only genuinely two-device workflow in the application, and it costs one query
parameter and one screen.

### Phone access

**Milestone 1 is web only.** The responsive web app is opened in the phone's browser over
the tailnet. This is already a working phone experience, not a
placeholder for one.

Photo capture in milestone 1 uses a plain file input:

```html
<input type="file" accept="image/*" capture="environment">
```

Tapping it opens the phone's own camera app, and the photo comes back as a file. No
permissions dialog to manage, no camera code to write, works on both platforms.

#### Secure context: already satisfied

**Live in-page camera preview (`getUserMedia`) and PWA installation both require a secure
context**: HTTPS or `localhost`. A plain `http://192.168.1.10:8000` does not qualify, and
browsers refuse both, silently in some cases.

**This is a non-issue in the target deployment.** Caddy serves the app over HTTPS with a
real certificate on a stable hostname, on the LAN and over the tailnet alike (§9). Every
option below is therefore available, and the milestone 2 decision can be made on merit
rather than on what the transport permits.

The plain file input above needs no secure context either, so milestone 1 also works
unchanged in a plain-HTTP development setup.

#### Milestone 2 options

| Option | Camera | Effort | Distribution |
|---|---|---|---|
| **PWA**: manifest + service worker on the existing app | Same file input, or live preview once on HTTPS | ~1 day. No new language, no new toolchain, no second codebase. | "Add to Home Screen". No store, no signing, no Apple Developer account. |
| **Capacitor**: native shell around the same web app | Native camera plugin; best-in-class capture flow | Moderate. No UI rewrite, but Xcode / Android Studio, signing, build pipeline. | Sideloaded APK, or TestFlight on iOS. |
| **React Native / Expo**: a real native app | Excellent, full control | High. A second UI codebase; only types and the API client are shared. | Store or sideload; iOS needs a paid account for anything beyond 7-day rebuilds. |
| **Native Swift / Kotlin** | Excellent | Very high, and two of them | Not seriously considered. |

#### On "snappy"

Worth being blunt about where the milliseconds actually are, because the intuition that
native is faster does not apply well here.

Perceived speed in this app is dominated by three things: how fast it launches, how fast
search responds, and how long a photo upload takes. Search is a SQLite query over a few
thousand rows on the local network, sub-millisecond, and identical whatever the client is.
Upload is bounded by the photo's size and the WiFi. Launch is the only place native wins,
by perhaps a couple of hundred milliseconds, and a PWA with a cached app shell closes most
of that.

What actually makes it feel fast is unglamorous and available to every option above: cache
the app shell, debounce the search input, downscale images on the client before upload, and
update the UI optimistically instead of waiting for the round trip. Those are already in
the milestone 1 requirements.

#### Direction

**Leaning PWA, decided at milestone 2, not now.** It reuses the entire React codebase,
introduces no new language or build system, and needs no app store, signing key, or
developer account, which matters for a tool with exactly one user. Its real cost is
requiring HTTPS, which the existing Caddy setup already provides.

The honest trigger for reconsidering is the camera flow. The file input hands you off to
the camera app and back, once per photo; if cataloguing a box of thirty things makes that
feel like wading, Capacitor's native capture is the targeted fix, and because it wraps the
same web app, switching costs a build pipeline rather than a rewrite.

React Native is the right answer only if this stops being a personal tool.

---

## 9. Deployment

One Docker image, one volume.

The frontend is built at image build time and the static output is served by FastAPI. One
service, one port, no CORS configuration, no second container.

```
/data/
  inventory.db          live SQLite database (+ -wal, -shm)
  blobs/                image blobs; never deleted except by `gc` (§7.6)
  tmp/                  scratch for atomic writes; excluded from backups
  config.toml           secrets and settings
  backup/inventory.db   consistent snapshot, written by POST /api/admin/backup
```

Everything lives on a single mounted volume, so backup is a directory copy (§7.6).

**Configuration lives in `/data/config.toml`, not only in environment variables.** This is
deliberate: with the session key held solely in a compose file, a copy of the volume is
*not* a complete backup, and restoring onto a new machine would invalidate every session.
The file is created on first run with a generated `secret_key` if absent, and is written
atomically (temp file, then `os.replace`) so a backup never catches it half-written.

| Setting | `config.toml` key | Env override | Purpose |
|---|---|---|---|
| Session key | `secret_key` | `SECRET_KEY` | Cookie signing key. Generated on first run. |
| Backup token | `backup_token` | `BACKUP_TOKEN` | Token for `POST /api/admin/backup`. **Not** generated; endpoint disabled if unset. See below. |
| Cookie security | `session_cookie_secure` | `SESSION_COOKIE_SECURE` | Default `false`; `true` in this deployment. |
| Data directory | (none) | `DATA_DIR` | Default `./data`; the Dockerfile sets `/data`. |

Environment variables take precedence, so secrets can still be injected rather than stored
when that is preferred.

**Login credentials are not here.** They live in the `users` table (§5), set with
`python -m boxes3.set_password <username>`. They are therefore covered by the
database snapshot rather than by this file.

### Setting the backup token

`secret_key` is generated on first run because a missing one would simply break the app.
`backup_token` is **not**, and the difference is deliberate. A generated backup token would
mean every fresh clone boots with a live admin endpoint behind a secret nobody chose and
nobody knows they have. Absent means off, and turning it on is an explicit act.

To turn it on, add a line to `config.toml`:

```toml
backup_token = "..."
```

or inject `BACKUP_TOKEN`. **There is deliberately no command for this.** It is one line
in one file, written once and rotated rarely, and a command to write it would be more
machinery than the job needs. Add one later if that stops being true.

**The backup script should read the token from `config.toml` rather than keep its own
copy**, so there is one place to rotate:

```sh
BACKUP_TOKEN=$(python3 -c 'import tomllib; print(tomllib.load(open("/data/config.toml","rb"))["backup_token"])')
```

This costs nothing. The script already has read access to every byte of `/data`, the
database included, so the token is not a boundary against *it*. The token is a boundary
against everything else reachable on the LAN and the tailnet.

`config.toml` is created mode `0600`. It holds a signing key and this token.

### TLS and reverse proxy

**The application speaks plain HTTP and never terminates TLS.** Caddy, already running in
the target environment, terminates TLS with a real certificate for a subdomain of a domain
the author controls. Split-horizon DNS resolves that hostname to a LAN address at home and
to a tailnet address elsewhere, so the same HTTPS URL works in both places.

There are two connections, with different properties, and it matters which is which:

```
Browser ──https://host.example.org──► Caddy ──http://app:8000──► FastAPI
        └─ encrypted; the connection   └─ terminates   └─ plain HTTP,
           the browser judges             TLS             always
```

The container exposes one plain-HTTP port and Caddy is the only thing in front of it. The
application has no knowledge of Caddy or Tailscale; both are transport.

**What follows from the browser side, not from the app's socket:**

*Secure-context browser APIs are available.* `getUserMedia`, service workers and PWA
installation are judged against the URL in the browser's address bar, which is HTTPS. The
app's own protocol is irrelevant to that. This is why the milestone 2 constraint in §8
("Phone access") does not apply here.

*`session_cookie_secure` is `true`.* This is not a requirement on the app, but one word
in a `Set-Cookie` header instructing the *browser* to send the cookie only over HTTPS. A
plain-HTTP app sets it perfectly well. It guards the case where a stale bookmark or a typed
hostname reaches `http://` before Caddy can redirect. It stays configurable because it must
be `false` when bypassing Caddy to reach the container directly in development.

**What the app must do differently behind a proxy: essentially nothing.**

*Relative URLs only.* The frontend is served from the same origin as the API, so it uses
relative paths, and nothing in the app constructs an absolute `http://…` URL. With that,
the app never needs to know its own scheme or hostname, and therefore needs no
`X-Forwarded-*` handling and no proxy flags on the server.

> Uvicorn is the ASGI server that binds the port and speaks HTTP to Caddy; FastAPI is the
> framework running inside it. It arrives with `fastapi[standard]` and is what `fastapi
> dev` and `fastapi run` invoke. No special flags are required.

**No rate limiting, anywhere in this application.** Deliberate. Login brute-forcing is the
threat it would address, and the app is reachable only from the LAN and the tailnet, never
the open internet. An attacker must already hold a device on one of those networks.

**If it is ever wanted, it belongs in Caddy, and the application stays unaware of it.** This
works cleanly rather than by accident: Caddy terminates TLS and is what the client actually
connects to, so it sees the real client address directly, no forwarded headers, no trust
decisions, and rejects the request before proxying it. The app never receives it. Nothing
to implement, nothing to configure, no reason for the app to know its client's IP. That is
why removing the client-IP dependency in this section was a simplification and not a
trade-off.

Two details for whoever sets that up later:

- Scope the limit to the login path (`/api/auth/login`) rather than the whole site.
  Limiting everything throttles ordinary browsing, and image requests especially.
- Caddy's rate limiting is a **plugin** (`caddy-ratelimit`), not part of the standard
  binary, so it needs a Caddy build that includes it, via `xcaddy`, or the plugin-selected
  download. It is a Caddy-side task either way; the application is untouched.

### Running locally over plain HTTP

**This is a public repository.** Cloning it and running the app over plain HTTP, with no
reverse proxy and no certificates, is a supported configuration and must stay that way. The
Caddy setup in the previous section is *the author's deployment*, not a requirement.

**All of milestone 1 works over plain HTTP.** This is not a reduced mode with caveats
attached. It is the full feature set.

#### Why it works: the localhost exemption

Browsers grant "secure context", the privilege level that gates cameras, service workers
and similar APIs, to HTTPS origins **and to `http://localhost`, `http://127.0.0.1` and
`http://[::1]`**. Localhost is exempt by design, on the reasoning that traffic never touches
a network.

So a developer at `http://localhost:8000` has every browser capability available. The
exemption is what is unusual; HTTPS is simply the general case.

#### What is affected, and where

| Feature | `http://localhost` | `http://192.168.x.x` (LAN/phone) | HTTPS |
|---|---|---|---|
| Everything in milestone 1 | ✅ | ✅ | ✅ |
| Photo capture (`<input capture>`) | ✅ | ✅ | ✅ |
| Login / sessions | ✅ | ✅ | ✅ |
| Live camera preview (`getUserMedia`), M2 | ✅ | ❌ blocked | ✅ |
| PWA install / service worker, M2 | ✅ | ❌ blocked | ✅ |

The only column with gaps is **reaching a plain-HTTP server from another device**, such as
opening `http://192.168.1.50:8000` on a phone. That is not a secure context, so the
milestone 2 features are unavailable there. Milestone 1 is unaffected, because
`<input type="file" capture>` is an ordinary file input rather than a privileged API, which
is a reason to prefer it beyond its simplicity.

Anyone wanting the milestone 2 features from a phone needs TLS from somewhere: a reverse
proxy as in §9, or a tunnel. That is a deployment choice, not an application change.

#### Requirements for a fresh clone

- **`uv sync && uv run fastapi dev` must work with no configuration.** `DATA_DIR` defaults
  to `./data`, created on first run.
- **`session_cookie_secure` defaults to `false`.** See §5.
- **Setting a password is an explicit step, not magic.** A fresh install has no users. The
  app creates `config.toml` and generates `secret_key` on first run, then logs an
  instruction to run `python -m boxes3.set_password <username>`. No password is
  generated, and none is printed to stdout.
- **The README must state plainly that plain HTTP is supported**, that localhost is a secure
  context, and that the only limitation is milestone 2 features when reaching a plain-HTTP
  server from another device.
- **Frontend development** runs Vite's dev server proxying `/api` to the backend, so the
  browser sees a single origin and cookies behave exactly as in production.

## 10. Testing

Proportionate to a single-user tool: enough to refactor without fear, not enough to become
a second project.

**Backend: pytest, and this is where the coverage goes.**

- The `InventoryDatabase` implementation directly, against a temp-file SQLite database (not
  `:memory:`, WAL mode and the pragmas of §7.2 are part of what is being tested).
- The API through `httpx.AsyncClient` against the app: auth, CRUD, the search filters, and
  the error codes of §6.0.
- **Backup and restore end to end**, as an actual test: write data, call the backup
  endpoint, restore the snapshot into a fresh directory, assert the data is there. §7.6
  says this procedure must be tested once deliberately; making it a test is how it stays
  tested.
- **`gc`**, asserting that it removes orphans and *never* removes a blob still referenced,
  including the deduplicated case where two items share one image key.
- **The image pipeline**, which is the most algorithmic code in the application: hash the
  original, store it byte-identical, then decode, apply EXIF orientation, strip remaining
  metadata, resize to both derived variants, and re-encode. Cover each accepted input
  format including HEIC, a portrait photo carrying an orientation tag, oversized input
  rejected with `413`, and an unsupported type rejected with `415`. Assert specifically
  that the stored `original` is **byte-identical** to what was uploaded. That is the whole
  point of retaining it, and it is easy to break with a well-meaning normalisation step.
- **`regenerate_images`**, asserting that re-deriving variants under an unchanged key
  leaves `image_key` and the `original` byte-identical while replacing `full` and `thumb`.
- **That no internal identifier ever appears in a response.** Walk every endpoint's JSON
  and assert no `user_id`, and no `id` that parses as an integer. This is worth a real test
  rather than review vigilance: the `model_validate(row)` pattern (§12) silently picks up
  any column the model declares, so one stray field on a response model leaks internal keys
  everywhere that model is returned.
- **Search, treated as a behavioural contract rather than an implementation test.** §6.3
  promises that `q` can move from `LIKE` to FTS5 without touching the API. What makes that
  true is a suite asserting *behaviour*: this query finds that item, filters compose,
  `tag` is conjunctive, results come back in server order. That suite then runs unchanged
  against the new implementation. Without it the upgrade path is a promise, not something
  verifiable.
- Schema creation via Alembic migrations, so the migration path is exercised rather than
  assumed (§7.5).

**`pylib`: its own suite, in its own repository.** The atomic-write behaviour of §2.2 is
the part worth testing hard: assert that a concurrent reader never observes a partial file,
and that overwriting an existing id replaces it cleanly rather than truncating in place.
Note there is nothing to test about content verification or write-once refusal, since
the store does neither, by design.

**Frontend: minimal.** A smoke test that the app renders and login works. No component-level
unit tests; the generated types already catch the class of error that matters most, and
hand-written UI tests for a personal tool cost more than they return.

### When and how

**Tests ship with the code that they test, in the same change.** Not deferred to a later
pass. A phase is not finished until its tests exist and pass. This is stated because the
alternative reliably produces an implementation followed by an offer to add tests
afterwards, and the tests then never carry the same weight.

```
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
```

**Ruff is the quality gate**, configured as in `no-more-paper-2` (§12): rules
`E,F,I,B,UP,ANN,FAST`, with `ANN` relaxed for the test suite. No separate type checker:
`ANN` already forces annotations, FastAPI and Pydantic validate at runtime, and mypy against
SQLAlchemy Core produces more noise than signal at this size.

**CI: GitHub Actions**, on push and pull request, for **both** repositories. One job: install
with `uv`, run ruff, run pytest.

The `pylib` half is the part that earns its keep. `boxes3` pins a `pylib` git tag
(§2.3), so a tag pushed with a broken build becomes *this* project's problem at the next
`uv lock`. CI on `pylib` catches it at the tag instead. Both repositories being public also
means a stranger's pull request gets checked without you running anything locally.

---

## 11. Scope

### Milestone 1: in scope

Everything above, in roughly this order:

0. **Create the `pylib` repository** and extract the blob store into it (§2.2) with the
   atomic-write change, tests passing, then tag `v0.1.0` and push so
   `boxes3` can depend on it (§2.3). This comes first because image handling depends
   on it.
1. Backend: schema, `InventoryDatabase` ABC + SQLite implementation, auth, box and item
   endpoints, image endpoints.
2. Frontend: generated API client, login, search, item and box screens, master-detail
   layout above 900px, the "pack a box" bulk entry mode, and the phone photo pass.
3. Dockerfile, one container, one volume, behind Caddy.

Feature-wise: password login, box CRUD, item CRUD, one image per item, simple search over
titles and tags, responsive web UI serving both the phone lookup job and the laptop entry
job, and a backup endpoint.

### Milestone 1: explicitly out of scope

Multiple users, registration, or password reset. Rate limiting (§9). Multiple images per
item. Item quantities. Barcode or QR scanning. Nested boxes or containers-within-containers.
Move history. Export or import. Offline support. Full-text search.

### Milestone 2: known future work

**Exception / status field.** The ability to record that an item isn't where it says it is,
most likely "lent out to Kalle". **Undecided by design**, because the right shape depends on
usage that hasn't happened yet:

- *Free text `note`*: flexible, captures any exception, but not queryable.
- *Structured `lent_to`*: queryable ("what have I lent out?"), but presumes lending is the
  exception that matters.

Deferring costs nothing: adding an optional field to a Pydantic response model is
non-breaking, since existing clients ignore fields they don't know. Decide after living
with the tool.

**FTS5 search.** Per §6.3, behind the unchanged API contract.

**Phone app.** Milestone 1 is web only; the responsive web app in a browser is the phone
experience. Milestone 2 revisits this, leaning towards a PWA. Options, the HTTPS constraint
that shapes them, and where the milliseconds actually are: §8, "Phone access".

**Phone-as-camera during laptop entry.** An optional comfort upgrade over the photo pass
(§8): attach a photo to an item *while typing it* on the laptop, rather than in a second
pass. Deliberately not milestone 1, since the photo pass already ensures every item
gets a
photo, so this changes the motion, not the outcome. Judge it after packing a few real
boxes.

Sketch, if it is ever built:

1. The laptop form calls `POST /api/capture-sessions`, creating a short-lived row and
   returning a URL such as `/capture/<session-id>`.
2. The laptop renders that URL as a QR code.
3. The phone scans it, opens the page, and uploads via
   `PUT /api/capture-sessions/<id>/image` using the same `<input capture>` control.
4. The laptop polls `GET /api/capture-sessions/<id>` once a second, shows the thumbnail
   when it lands, and creates the item with `image_key` already set.

Roughly a `capture_sessions` table, three endpoints, expiry cleanup, a QR library, a polling
hook and a capture page, a day or two.

**Two notes that materially reduce the cost and risk:**

*Do not put a credential in the QR.* The obvious design has the URL token authorise the
upload, which introduces the first unauthenticated write path in the application, exactly
where things go wrong. Unnecessary here: the phone is already logged in on the same origin
with a 30-day cookie, so the QR can be a plain deep link and normal session auth applies.
The session id becomes an identifier, not a key.

*The QR may not be needed at all.* With a single user there is no ambiguity about whose
capture session is pending, so the phone can simply display it, "your laptop is waiting for
a photo of *hammer*", with no scanning and no camera-app detour. Fewer moving parts, and
plausibly faster in the hand.

---

## 12. Reference material in `no-more-paper-2`

To be read, not imported. Useful patterns already worked out there:

| Pattern | Worth copying |
|---|---|
| `db/document_database.py` | Abstract base class over the storage layer, with domain-specific exceptions (`DocumentNotFoundError`) rather than leaked SQL errors. |
| `db/sqlite/document_database.py` | SQLAlchemy Core with `.returning(*table.c)` and `Model.model_validate(row)`, no ORM session management. |
| `db/sqlite/schema.py` | Table definitions as `Table` objects against a shared `MetaData`. |
| `api/documents.py` | Thin routers translating database exceptions into `HTTPException`. |
| `blob/blob_store.py`, `blob/filesystem_blob_store.py` | The blob store, **copied out into `pylib` (§2.2)**, not imported from here. Generic already, but **one behavioural change is required**: `put` must write atomically (temp file, `fsync`, `os.replace`) so a backup never copies a half-written file. It stays a dumb byte store otherwise, no hashing, no content verification, overwrites permitted. See §2.2. |
| `pyproject.toml` | Ruff configuration (`E,F,I,B,UP,ANN,FAST`) and `uv` layout. |

Deliberate departures from that code:

| There | Here | Why |
|---|---|---|
| `x_user_id` request header | `Depends(get_current_user)` | That header is unauthenticated; anyone could claim any user. |
| `Document` model carrying `id: int` and `user_id: int` | Response models carry **only** the external id | Those fields exist on the reference model and would be serialised straight into responses by `model_validate(row)`. Keep internal and API models separate (§6.0). |
| `DocumentState` (draft/active) | *removed* | Items have no lifecycle; they are in a box or they don't exist. |
| Counter-assigned `index_number` | User-typed box number with a suggested default | The number is written on a physical box, sometimes before this tool sees it. |
| Bare `list[DocumentOut]` responses | Envelope with `next_cursor` | A bare array has nowhere to grow. |
| `random.choice` for public ids | `secrets.choice` | `random` is not cryptographically secure. |
