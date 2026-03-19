# INV-CONFIG-VALIDATION-AUTHORITY

## Behavioral Guarantee

Schema validation of configuration data MUST execute unconditionally on every production code path that loads `config/defaults.yaml` or parses a channel YAML file. No production caller may bypass, skip, or suppress schema validation.

## Authority Model

The config loader (`config_loader.py`) and resolver (`resolver.py`) own validation enforcement. The schema module (`schema.py`) owns the structural definition. The testing module (`testing.py`) owns the bypass surface for test fixtures.

## Boundary / Constraint

- `load_defaults()` MUST NOT accept a parameter that disables validation.
- `resolve_channel_config()` MUST NOT accept a parameter that disables validation.
- `resolve_defaults_only()` MUST NOT accept a parameter that disables validation.
- The internal `_load_defaults_impl(_validate=False)` MUST NOT appear in `__all__` of any public module.
- The only callers of `_load_defaults_impl(_validate=False)` MUST be functions in `retrovue.config.testing`.
- Production source files under `src/retrovue/` (excluding `config/testing.py`) MUST NOT import `_load_defaults_impl`.
- Test fixtures that use intentionally incomplete YAML MUST use `load_defaults_unvalidated()` or `resolve_channel_unvalidated()` from `retrovue.config.testing`.

## Violation

- A production code path loads config without schema validation.
- A public function signature exposes a `validate` parameter.
- `_load_defaults_impl` is called from outside `retrovue.config.testing`.
- An invalid `defaults.yaml` or channel YAML reaches a runtime component.

## Required Tests

- `pkg/core/tests/contracts/test_config_validation_authority.py`

## Enforcement Evidence
TODO
