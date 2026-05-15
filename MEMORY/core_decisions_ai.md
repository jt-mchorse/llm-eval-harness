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

- id: D-004
  date: 2026-05-15
  decision: judge_backend_is_single_method_protocol_for_test_swap
  rationale: tests_substitute_deterministic_stub_no_api_key_required_for_unit_tests
  alternatives_rejected: [hard_coded_anthropic_client, abstract_base_class, dependency_injection_container]
  reversibility: cheap
  related_issues: [2, 3]
  superseded_by: null

- id: D-005
  date: 2026-05-15
  decision: calibration_metrics_kappa_binarized_plus_pearson_continuous_only_kappa_gates_ci
  rationale: kappa_is_classification_correctness_pearson_catches_systematic_bias_kappa_misses
  alternatives_rejected: [kappa_only, pearson_only, mse_or_mae, accuracy_at_threshold]
  reversibility: cheap
  related_issues: [2]
  superseded_by: null

- id: D-006
  date: 2026-05-15
  decision: calibration_set_self_labeled_with_explicit_disclosure_50_rows_distributed_across_score_axis
  rationale: small_n_single_labeler_honest_about_limits_better_than_pretending_multi_rater
  alternatives_rejected: [require_multi_rater_before_shipping_judge, ship_judge_without_calibration, generate_set_with_an_llm]
  reversibility: cheap
  related_issues: [2]
  superseded_by: null
