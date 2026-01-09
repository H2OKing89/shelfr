# C3: Document commands/ vs cli/ Structure

**Priority**: Low
**Effort**: Low
**Risk**: Low

---

## Problem

Two parallel systems exist for CLI commands:

1. `src/shelfr/commands/` - Handler implementations
2. `src/shelfr/cli/` - Typer command registration

This creates confusion about where to add new functionality.

## Target State

Document the pattern in `CONTRIBUTING.md`:

```markdown
## CLI Architecture

### Structure

- `cli/` - Typer command registration, argument parsing, thin wrappers
- `commands/` - Business logic implementation, no CLI dependencies

### Adding a New Command

1. Create handler in `commands/`:
   ```python
   # commands/myfeature.py
   def cmd_my_feature(ctx: RuntimeContext, arg1: str) -> int:
       """Business logic here."""
       return 0
   ```

2. Register in `cli/`:

   ```python
   # cli/myfeature.py
   @app.command()
   def my_feature(arg1: str = typer.Argument(...)):
       """CLI wrapper."""
       return cmd_my_feature(get_context(), arg1)
   ```

```

## Acceptance Criteria

- [ ] Pattern documented in `CONTRIBUTING.md`
- [ ] Example shown for adding new commands
