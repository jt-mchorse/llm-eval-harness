# Core Decisions (AI-readable, YAML, append-only)
# Schema: see .skills/portfolio-memory/SKILL.md

- id: D-001
  date: 2026-05-10
  decision: scope_per_portfolio_handoff_section_2
  rationale: locked_scope_prevents_drift
  alternatives_rejected: []
  reversibility: expensive
  related_issues: []
  superseded_by: null

- id: D-002
  date: 2026-05-11
  decision: expected_outputs_as_list_of_typed_objects_kind_value
  rationale: forward_compat_with_judge_wrapper_without_schema_rev
  alternatives_rejected: [list_of_plain_strings, single_string_expected]
  reversibility: cheap
  related_issues: [1, 2]
  superseded_by: null

- id: D-003
  date: 2026-05-11
  decision: dataset_version_is_opaque_metadata_one_version_per_file
  rationale: authors_own_versioning_convention_loader_enforces_consistency
  alternatives_rejected: [semver_required_by_harness, mixed_versions_in_one_file]
  reversibility: cheap
  related_issues: [1, 6]
  superseded_by: null
