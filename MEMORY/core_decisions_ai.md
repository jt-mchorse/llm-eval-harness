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

- id: D-012
  date: 2026-05-16
  decision: pytest_plugin_parametrizes_via_pytest_generate_tests_not_collection_modifyitems
  rationale: parametrize_path_works_with_pytest_k_collect_only_and_xdist_synthesizing_items_in_modifyitems_would_break_those_integrations
  alternatives_rejected: [collection_modifyitems_full_ownership, custom_pytest_item_subclass, helper_function_called_from_each_test]
  reversibility: cheap
  related_issues: [#5]
  superseded_by: null

- id: D-013
  date: 2026-05-16
  decision: threshold_assertion_lives_in_pytest_pyfunc_call_hookwrapper_not_autouse_fixture_teardown
  rationale: fixture_teardown_assertion_error_counts_as_test_error_not_test_failure_pytest_pyfunc_call_keeps_assertion_in_call_phase
  alternatives_rejected: [autouse_fixture_with_pytest_fail_in_teardown, custom_runtest_method_on_a_subclassed_item, force_users_to_write_explicit_assert]
  reversibility: cheap
  related_issues: [#5]
  superseded_by: null

- id: D-014
  date: 2026-05-16
  decision: drift_axes_use_jensen_shannon_divergence_base_2_bounded_zero_to_one
  rationale: kl_is_unbounded_and_asymmetric_ks_only_works_on_ordered_scalars_so_it_does_not_generalize_to_the_cluster_id_axis_jsd_does_both_with_one_formula_and_one_threshold_per_axis
  alternatives_rejected: [kl_divergence_either_direction, kolmogorov_smirnov_statistic, total_variation_distance, wasserstein_extra_dep]
  reversibility: cheap
  related_issues: [#4]
  superseded_by: null

- id: D-015
  date: 2026-05-26
  decision: atomic_write_helpers_live_in_package_level_io_utils_module_not_file_private
  rationale: portfolio_standard_emerged_from_2026_05_26_atomic_write_arc_rag_kit_io_utils_atomic_write_text_was_first_in_pr_44_45_other_repos_followed_keeping_helper_private_in_cli_py_was_the_outlier
  alternatives_rejected: [keep_helper_file_private_in_cli_py, split_into_one_helper_per_call_site_file, ship_a_separate_distribution_package]
  reversibility: cheap
  related_issues: [#48, #50]
  superseded_by: null

- id: D-016
  date: 2026-07-07
  decision: non_strict_mypy_gate_as_baseline_strictness_bar
  rationale: py_typed_146_ships_annotations_downstream_but_nothing_machine_checked_them_here_so_they_could_silently_drift_non_strict_baseline_keeps_them_honest_without_the_churn_of_full_strict_mode_no_blanket_ignore_missing_imports_so_typod_imports_still_surface_per_module_override_only_for_optional_anthropic_sdk_warn_unused_ignores_plus_warn_redundant_casts_on
  alternatives_rejected: [full_strict_mode_disallow_untyped_defs_now, blanket_ignore_missing_imports, no_gate_leave_annotations_unchecked, pyright_instead_of_mypy]
  reversibility: cheap
  related_issues: [#146, #148]
  superseded_by: null

- id: D-017
  date: 2026-08-24
  decision: zero_hash_embed_vector_means_uncomparable_reject_on_authored_golden_side_count_on_sampled_candidate_side
  rationale: hash_embed_returns_the_all_zero_vector_for_an_input_with_no_alphanumeric_tokens_and_cosine_of_the_zero_vector_is_exactly_0_0_so_such_an_input_scored_distance_1_000_the_ceiling_of_the_range_and_because_representative_examples_is_truncated_it_did_not_merely_rank_wrongly_it_evicted_every_input_with_real_content_5_of_5_slots_went_to_punctuation_and_the_same_tie_made_assign_put_all_of_them_in_cluster_0_moving_the_published_embedding_jsd_from_0_1909_to_0_3122_the_zero_vector_is_not_a_point_at_some_angle_it_is_the_absence_of_a_point_so_every_cosine_derived_quantity_for_it_is_undefined_not_maximal_the_remedy_splits_by_side_because_the_two_sides_have_different_economics_a_golden_set_is_authored_small_and_fixable_so_one_with_nothing_embeddable_fails_loud_measured_it_was_accepted_and_reported_0_000_ok_a_maximal_false_negative_from_a_baseline_that_can_measure_nothing_a_candidate_set_is_a_sampled_traffic_slice_so_one_emoji_must_not_abort_a_10k_line_run_those_are_counted_in_the_new_drift_report_n_uncomparable_field_and_excluded_from_the_cluster_histograms_and_the_example_list_the_length_and_judge_axes_still_see_them_because_a_char_count_is_truthful_and_a_judge_can_legitimately_score_them
  alternatives_rejected: [exclude_silently_without_reporting_a_count_loses_the_junk_traffic_signal, reject_uncomparable_candidate_inputs_at_ingest_a_single_emoji_would_abort_a_10k_line_drift_run, keep_them_and_give_them_their_own_histogram_bucket_changes_cluster_counts_length_and_the_meaning_of_a_cluster_id_for_every_consumer, leave_it_and_document_the_skew_as_accepted, change_hash_embed_itself_to_char_ngram_backoff_moves_every_already_published_number_and_is_a_different_question_from_what_the_zero_vector_means]
  reversibility: cheap
  related_issues: [#210, #208]
  superseded_by: null


- id: D-018
  date: 2026-08-26
  decision: unrepresentable_input_rejected_on_both_drift_sides_d017_asymmetry_does_not_extend
  rationale: a_lone_surrogate_has_no_utf8_encoding_so_the_html_report_cannot_be_written_at_all_d017_lets_token_less_candidate_rows_through_because_they_are_representable_but_unembeddable_and_one_emoji_must_not_abort_a_10k_line_traffic_slice_but_that_argument_is_about_embeddability_not_representability_dropping_the_row_instead_would_deflate_n_candidate_and_both_histograms_with_no_diagnostic_which_is_the_same_false_negative_class_as_91_and_93
  alternatives_rejected: [extend_d017_split_and_exclude_unencodable_candidate_rows_from_the_report, sanitize_with_errors_surrogatepass_or_replacement_char, catch_unicodeencodeerror_at_the_write_seam_only]
  reversibility: cheap
  related_issues: [#215, #213, #210]
  superseded_by: null
