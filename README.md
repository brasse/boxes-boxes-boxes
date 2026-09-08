# Boxes Boxes Boxes

Track which numbered box a thing is stored in, searchable from a laptop or a phone.

`SPEC.md` is the contract. `PLAN.md` is the build order.

```
uv sync
uv run fastapi dev src/boxes3/main.py
```

No configuration is needed on a fresh clone. The first run creates `./data` with a
generated session key.
