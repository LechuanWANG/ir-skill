# ADR 0003: Evolve SQLite only through versioned migrations

Schema extensions are registered with a version and name, applied transactionally once, and recorded in SQLite. Existing databases receive a verified backup before pending migrations run; the migration layer checks database integrity before reporting success.
