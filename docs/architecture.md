# Architecture

Vekna uses the **GLIMPSE** layering model. Import boundaries are enforced by
`import-linter` (contracts in `pyproject.toml`).

## Layers

```
pacts   Protocols, DTOs, errors, enums, TypedDicts. Depends on nothing.
specs   Business invariants — pure constants, no IO. Depends on pacts.
mills   Business logic and services. Depends on pacts + specs only.
links   I/O adapters (sockets, tmux). Depends on pacts.
gates   Entry points (CLI commands). Depends on pacts + mills.
inits   Wiring — registers handlers, starts background tasks.
edges   Infrastructure boundary (wsgi/asgi, manage, settings).
```

### Import rules (enforced)

| Layer   | May import              | May NOT import                            |
|---------|-------------------------|-------------------------------------------|
| `pacts` | stdlib, third-party     | any internal layer                        |
| `specs` | pacts                   | mills, links, gates, inits, edges         |
| `mills` | pacts, specs            | links, gates, inits, edges                |
| `links` | pacts                   | mills, gates, inits, specs, edges         |
| `gates` | pacts, mills            | links, inits, specs, edges                |
| `inits` | pacts, mills, links, gates | edges                                  |
| `edges` | stdlib, third-party     | all internal layers                       |

## File layout

Every layer is a package (directory with `__init__.py`), never a single `.py`
file. Minimum shapes:

```
pacts/{subdomain}.py
specs/{subdomain}.py
mills/{subdomain}.py
links/{port}/{adapter}.py          # e.g. links/socket/asyncio_.py
gates/{port}/{adapter}/{subdomain}.py  # e.g. gates/cli/click/vekna.py
inits/{subdomain}.py
```

Split a file at ~1000 lines or when two unrelated concerns create merge
friction. Never create nested folders before files exist to fill them.

### Ports and adapters

- **Port** — delivery mechanism named after the domain concept: `cli`, `socket`, `tmux`
- **Adapter** — specific technology: `click`, `asyncio`, `libtmux`

Current layout:

```
pacts/
  bus.py       # EventBus contracts
  notify.py    # Notification DTOs and protocols
  server.py    # Server request/response DTOs
  socket.py    # Socket protocol types
  tmux.py      # Tmux protocol types
specs/
  attention.py # Idle-time thresholds
  session.py   # Session naming constants
mills/
  bus.py       # EventBus implementation
  handlers.py  # ClaudeNotificationHandler, SelectPaneHandler
  notify.py    # NotifyClientMill
  server.py    # ServerMill
links/
  socket_client.py   # Unix socket client adapter
  socket_server.py   # Unix socket server adapter
  tmux.py            # libtmux adapter
gates/
  cli/click/
    command.py       # Click command group
inits/
  cli.py       # Wires links → mills → gates, starts background tasks
```

## Patterns

1. **Mills are I/O-free.** Only protocols and DTOs from `pacts`. No socket,
   tmux, or filesystem calls inside `mills/`.
2. **Links implement protocols from pacts.** Each link adapter implements a
   `Protocol` defined in `pacts/`. Mills depend on the protocol, never the
   concrete link.
3. **Gates call mills, not links.** Entry points wire through `inits`, not by
   importing links directly.
4. **DTOs use Pydantic `BaseModel`.** Add
   `model_config = ConfigDict(from_attributes=True)` when constructing from
   external objects.
5. **Write shapes use TypedDicts.** DTOs for data flowing in; TypedDicts for
   write payloads passed between layers.
6. **Specs are constants only.** No functions, no IO, no logic — pure values
   consumed only by `mills`.

## Drift red flags

- A layer kept as a single `.py` file instead of a package
- Nested folders that hold only one or two small files
- `pacts/dtos.py`, `pacts/protocols.py`, or `pacts/errors.py` — split by
  subdomain, not by technical kind
- `common/` or `shared/` folder inside any layer
- A `mills/` file importing from `links/` (business logic calling I/O)
- `specs/` imported from `links/`, `gates/`, or `inits/`
- A `links/` file that holds business logic (validation, decisions)
- `gates/` importing from `links/` directly instead of going through `inits`
