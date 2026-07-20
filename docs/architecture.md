# IR Skill Architecture

IR Skill separates reusable research rules from user-owned research assets:

```text
SKILL.md router and specialist Skills
              ↓
Python scripts and versioned SQLite migrations
              ↓
Local Research Hub HTTP API (127.0.0.1 only)
              ↓
React/Vite Research Hub
```

- `SKILL.md` routes broad requests; specialist Skills own research methods; shared Markdown owns cross-cutting evidence and risk rules.
- `scripts/` provides deterministic collection, storage, migration, validation, and local HTTP capabilities. Existing CLI and JSON outputs are compatibility boundaries.
- Each user's project directory owns `.env`, `data/`, `report/`, Wiki, holdings, watchlists, and SQLite. The Skill installation stays read-only apart from normal development work.
- SQLite schema changes are versioned, transactional, idempotent, integrity-checked, and backed up before an existing database receives pending migrations.
- `web/` consumes only the local HTTP API; UI data loading and sync polling live in hooks so pages remain rendering-focused.
