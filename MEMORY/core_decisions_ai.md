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

- id: D-007
  date: 2026-05-15
  decision: answer_source_is_separate_protocol_from_judge_backend
  rationale: model_under_test_must_be_separable_from_judge_model_so_one_models_outputs_can_be_scored_by_another_models_judge
  alternatives_rejected: [merge_into_judge_backend_with_role_arg, single_backend_serves_both_roles]
  reversibility: cheap
  related_issues: [3]
  superseded_by: null

- id: D-008
  date: 2026-05-15
  decision: run_history_persisted_in_sqlite_two_tables_runs_and_rows_foreign_key_enforced
  rationale: stdlib_sqlite3_zero_deps_idempotent_create_table_if_not_exists_diffs_just_join_on_run_id
  alternatives_rejected: [json_lines_history_no_indexes, mongodb_or_postgres_overkill, no_persistence_only_in_memory_diff]
  reversibility: cheap
  related_issues: [3, 4, 6]
  superseded_by: null

- id: D-009
  date: 2026-05-16
  decision: sticky_pr_comment_identified_by_hidden_html_marker_not_by_author_or_title
  rationale: marker_based_identity_survives_bot_renames_token_rotations_and_consumers_calling_same_action_from_different_repos
  alternatives_rejected: [match_on_comment_author_username, match_on_title_prefix, single_comment_per_pr_via_locked_thread_metadata]
  reversibility: cheap
  related_issues: [6]
  superseded_by: null

- id: D-010
  date: 2026-05-16
  decision: diff_json_subcommand_operates_on_runresult_json_files_no_sqlite
  rationale: ci_runners_are_ephemeral_sqlite_history_is_for_local_dev_action_just_needs_one_current_vs_one_baseline
  alternatives_rejected: [persist_runs_to_sqlite_in_ci_then_diff, ship_sqlite_db_as_a_workflow_artifact, recompute_via_api]
  reversibility: cheap
  related_issues: [6, 7]
  superseded_by: null

- id: D-011
  date: 2026-05-16
  decision: top_level_calibrate_subcommand_with_judge_calibrate_kept_as_hidden_alias
  rationale: issue_7_public_surface_is_run_list_calibrate_diff_but_judge_calibrate_existed_first_breaking_existing_scripts_buys_nothing
  alternatives_rejected: [remove_judge_calibrate_entirely, keep_only_judge_calibrate_and_close_issue_7_as_naming_disagreement, alias_via_argparse_aliases_kwarg_loses_per_alias_help]
  reversibility: cheap
  related_issues: [#7]
  superseded_by: null
