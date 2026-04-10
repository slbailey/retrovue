"""INV-SCHEDULE-COMPILER-MODULE-SPLIT-001: Schedule compiler module boundary tests.

Verifies that:
1. Resolution symbols are importable from template_resolution.
2. Validation symbols are importable from schedule_validation.
3. All public symbols remain importable from schedule_compiler (re-exports).
4. Module boundaries are respected (no cross-concern leakage).
"""

import importlib
import inspect


# ---------------------------------------------------------------------------
# SPLIT-RESOLUTION-001: Resolution symbols exist in template_resolution
# ---------------------------------------------------------------------------

RESOLUTION_SYMBOLS = [
    "_resolve_template",
    "_resolve_template_for_program",
    "_resolve_presentation_ref",
    "_resolve_block_traffic_profile",
    "resolve_day_schedule",
    "resolve_scheduling_policy",
    "_PolicyAssetAdapter",
    "get_channel_template",
    "get_grid_minutes",
    "VALID_SCHEDULE_KEYS",
    "DOW_NAMES",
    "WEEKDAY_NAMES",
    "WEEKEND_NAMES",
    "_blocks_to_dict",
    "_ensure_list",
    "_FORBIDDEN_TEMPLATE_BREAK_FIELDS",
]


def test_resolution_symbols_importable_from_template_resolution():
    """SPLIT-RESOLUTION-001: All resolution symbols importable from template_resolution."""
    mod = importlib.import_module("retrovue.runtime.template_resolution")
    missing = [s for s in RESOLUTION_SYMBOLS if not hasattr(mod, s)]
    assert not missing, f"Missing symbols in template_resolution: {missing}"


# ---------------------------------------------------------------------------
# SPLIT-VALIDATION-001: Validation symbols exist in schedule_validation
# ---------------------------------------------------------------------------

VALIDATION_SYMBOLS = [
    "ValidationError",
    "_validate_templates",
    "_validate_grid_alignment",
    "_validate_start_grid_alignment",
    "validate_dsl",
    "validate_program_blocks",
    "_validate_traffic_profile_refs",
]


def test_validation_symbols_importable_from_schedule_validation():
    """SPLIT-VALIDATION-001: All validation symbols importable from schedule_validation."""
    mod = importlib.import_module("retrovue.runtime.schedule_validation")
    missing = [s for s in VALIDATION_SYMBOLS if not hasattr(mod, s)]
    assert not missing, f"Missing symbols in schedule_validation: {missing}"


# ---------------------------------------------------------------------------
# SPLIT-REEXPORT-001: All public symbols still importable from schedule_compiler
# ---------------------------------------------------------------------------

ALL_PUBLIC_SYMBOLS = sorted(set(RESOLUTION_SYMBOLS + VALIDATION_SYMBOLS + [
    # Compilation symbols that stay in schedule_compiler
    "CompileError",
    "AssetResolutionError",
    "ProgramBlockOutput",
    "compile_schedule",
    "parse_dsl",
    "channel_seed",
    "compilation_seed",
]))


def test_all_public_symbols_importable_from_schedule_compiler():
    """SPLIT-REEXPORT-001: All public symbols importable from schedule_compiler via re-exports."""
    mod = importlib.import_module("retrovue.runtime.schedule_compiler")
    missing = [s for s in ALL_PUBLIC_SYMBOLS if not hasattr(mod, s)]
    assert not missing, f"Missing re-exports in schedule_compiler: {missing}"


# ---------------------------------------------------------------------------
# SPLIT-BOUNDARY-001: template_resolution has no compilation functions
# ---------------------------------------------------------------------------

COMPILATION_FUNCTIONS = {
    "compile_schedule",
    "_compile_program_block",
    "parse_dsl",
    "_expand_to_compiled_segments",
    "_serialize_assembly_segment",
    "_compute_hash",
}

VALIDATION_FUNCTIONS = {
    "validate_dsl",
    "validate_program_blocks",
    "_validate_grid_alignment",
    "_validate_start_grid_alignment",
    "_validate_traffic_profile_refs",
    "_validate_templates",
}


def test_template_resolution_has_no_compilation_or_validation():
    """SPLIT-BOUNDARY-001: template_resolution contains no compilation or validation logic."""
    mod = importlib.import_module("retrovue.runtime.template_resolution")
    leaked_compilation = [s for s in COMPILATION_FUNCTIONS if hasattr(mod, s)]
    leaked_validation = [s for s in VALIDATION_FUNCTIONS if hasattr(mod, s)]
    assert not leaked_compilation, f"Compilation symbols leaked into template_resolution: {leaked_compilation}"
    assert not leaked_validation, f"Validation symbols leaked into template_resolution: {leaked_validation}"


# ---------------------------------------------------------------------------
# SPLIT-BOUNDARY-002: schedule_validation has no compilation or resolution functions
# ---------------------------------------------------------------------------

RESOLUTION_ONLY_FUNCTIONS = {
    "_resolve_template",
    "_resolve_template_for_program",
    "_resolve_presentation_ref",
    "_resolve_block_traffic_profile",
    "resolve_day_schedule",
    "resolve_scheduling_policy",
    "_PolicyAssetAdapter",
}


def test_schedule_validation_has_no_compilation_or_resolution():
    """SPLIT-BOUNDARY-002: schedule_validation contains no compilation or resolution logic."""
    mod = importlib.import_module("retrovue.runtime.schedule_validation")
    leaked_compilation = [s for s in COMPILATION_FUNCTIONS if hasattr(mod, s)]
    leaked_resolution = [s for s in RESOLUTION_ONLY_FUNCTIONS if hasattr(mod, s)]
    assert not leaked_compilation, f"Compilation symbols leaked into schedule_validation: {leaked_compilation}"
    assert not leaked_resolution, f"Resolution symbols leaked into schedule_validation: {leaked_resolution}"
