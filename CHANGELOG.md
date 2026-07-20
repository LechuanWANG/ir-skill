# Changelog

This project follows a compatibility-first change log.

## Unreleased

### Research Rules

- Added a root Skill router that preserves broad `ir-skill` discovery while delegating to specialist Skills.

### Data Schema

- Added versioned migration validation, pre-migration backups, and integrity checks for local SQLite evolution.

### CLI and API

- No intentional breaking changes to existing CLI parameters, JSON fields, or local Research Hub endpoints.

### UI

- Moved Research Hub data synchronization state and polling into a dedicated hook without changing the rendered API contract.
