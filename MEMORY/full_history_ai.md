# Session History (AI-readable, append-only)

Schema: see .skills/portfolio-memory/SKILL.md

---
session: 2026-05-11T19:00Z
duration_min: 55
issue: 1
focus: golden_dataset_jsonl_format
delta:
  files_changed: 7
  tests_added: 15
  benchmarks: {}
context_for_next_session:
  - dataset_layer_dep_free_so_safe_to_import_anywhere
  - pr_8_draft_awaiting_jt_review_before_merging_main
  - next_issue_2_judge_wrapper_consumes_expected_outputs_kind_semantic
decisions_made: [D-002, D-003]
followups: []
---

---
session: 2026-05-15T13:25Z
duration_min: 80
issue: 2
focus: judge_wrapper_plus_calibration_against_human_labels
delta:
  files_added: 5
  files_changed: 4
  tests_added: 36
  test_pass_rate: "51/51"
  fixtures_committed: 1   # 50-row calibration.jsonl
context_for_next_session:
  - judge_layer_shipped_anthropic_backend_plus_stub_via_protocol
  - calibration_layer_shipped_kappa_plus_pearson_50_row_set_committed
  - calibration_report_pending_operator_run_eval_harness_judge_calibrate
  - issue_1_closed_pr_8_was_merged_yesterday_just_lacked_closes_keyword
  - real_ci_now_running_lint_test_matrix_replaced_stub_echo
  - next_issue_3_regression_runner_consumes_dataset_plus_judge_both_shipped
decisions_made: [D-004, D-005, D-006]
followups: []
---

---
session: 2026-05-15T19:23Z
duration_min: 60
issue: 3
focus: regression_runner_plus_sqlite_persistence_plus_cli
delta:
  files_added: 4
  files_changed: 3
  tests_added: 17
  test_pass_rate: "68/68"
context_for_next_session:
  - runner_plus_diff_plus_run_persistence_shipped_via_sqlite_d008
  - answer_source_is_separate_protocol_from_judge_backend_d007
  - cli_subcommands_run_and_diff_exit_nonzero_on_flagged_regressions_default_threshold_drop_0_1
  - dataset_echo_source_is_the_hermetic_default_real_anthropic_answer_source_lands_when_consumer_needs_one
  - latest_run_id_for_suite_now_takes_exclude_run_id_kwarg_to_avoid_self_baseline_on_same_second_runs
  - smoke_test_runs_in_under_a_second_acceptance_criterion_was_under_10s
decisions_made: [D-007, D-008]
followups: []
---

---
session: 2026-05-16T04:00Z
duration_min: 40
issue: 6
focus: github_action_sticky_pr_eval_delta_comment
delta:
  files_added: 5
  files_changed: 4
  tests_added: 19
  test_pass_rate: "87/87"
context_for_next_session:
  - comment_module_renders_gfm_table_with_hidden_marker_d_009
  - sticky_marker_is_eval_harness_sticky_comment_html_comment_substring_first_match_wins
  - find_sticky_comment_paginates_per_page_100_caps_at_1000_total_comments_to_save_rate_limit
  - upsert_sticky_comment_refuses_body_without_marker_to_prevent_duplicates_next_run
  - github_api_plumbing_is_stdlib_urllib_request_no_pip_dep_token_via_github_token_env
  - diff_json_subcommand_d_010_takes_two_runresult_json_files_no_sqlite_emits_json_ascii_or_markdown
  - comment_subcommand_takes_repo_pr_delta_json_dry_run_for_local_testing
  - fixtures_demo_baseline_demo_current_committed_with_all_5_status_types_improved_unchanged_regressed_new_removed
  - workflow_eval_yml_runs_on_pull_request_against_main_uses_secrets_github_token_with_pull_requests_write_permission
  - tests_use_in_process_fake_github_server_via_api_base_override_not_mock_module
  - issue_6_acceptance_workflow_runs_on_pr_done_sticky_comment_pattern_done_table_renders_cleanly_done_demo_pr_is_this_pr
decisions_made: [D-009, D-010]
followups: []
---

---
session: 2026-05-16T15:45Z
duration_min: 30
issue: 7
focus: cli_list_subcommand_calibrate_alias_macos_ci_matrix
delta:
  files_added: 1  # tests/test_cli_list.py
  files_changed: 4  # cli.py, runs.py, ci.yml, README
  tests_added: 9
  test_pass_rate: "105/105"
context_for_next_session:
  - list_runs_helper_in_runs_py_returns_runsummary_list
  - eval_harness_list_subcommand_text_table_default_json_via_flag
  - calibrate_promoted_to_top_level_judge_calibrate_kept_as_hidden_alias_d_011
  - ci_test_matrix_now_os_ubuntu_macos_x_python_3_11_3_12_4_cells
  - cli_smoke_step_exercises_help_on_four_public_subcommands_per_cell
  - readme_quickstart_has_list_example_with_rendered_table
decisions_made: [D-011]
followups: []
---

---
session: 2026-05-16T15:53Z
duration_min: 40
issue: 5
focus: pytest_plugin_evals_as_tests
delta:
  files_added: 2  # pytest_plugin.py, test_pytest_plugin.py
  files_changed: 2  # pyproject.toml, README
  tests_added: 6
  test_pass_rate: "102/102"
context_for_next_session:
  - pytest_plugin_registered_via_pytest11_entry_point_marker_is_pytest_mark_eval
  - parametrize_via_pytest_generate_tests_d_012_keeps_k_collect_only_xdist_working
  - threshold_check_in_pytest_pyfunc_call_hookwrapper_d_013_so_failure_is_failed_not_error
  - judge_score_fixture_caches_per_row_eval_row_fixture_carries_the_example
  - autouse_ensure_judge_score_runs_forces_scoring_even_when_body_doesnt_reference_fixture
  - empty_dataset_fails_collection_via_load_jsonl_own_contains_no_examples_error
  - readme_quickstart_has_marker_example
decisions_made: [D-012, D-013]
followups: []
---

---
session: 2026-05-16T21:00Z
duration_min: 55
issue: 4
focus: drift_detection_length_embedding_cluster_judge_axes
delta:
  files_added: 5
  files_changed: 3
  tests_added: 24
  test_pass_rate: "126/126"
context_for_next_session:
  - drift_module_at_eval_harness_drift_three_axes_length_embedding_cluster_judge
  - jsd_base_2_bounded_zero_to_one_per_axis_threshold_per_axis_d_014
  - hash_embed_l2_normalized_dep_free_matches_rag_kit_pattern
  - kmeans_stride_init_deterministic_no_external_deps
  - judge_axis_skipped_when_judge_score_fn_is_none_so_hermetic_ci_still_renders_two_axes
  - cli_subcommand_eval_harness_drift_golden_candidate_output_judge_stub_cluster_k
  - smoke_fixtures_under_fixtures_drift_golden_identical_shifted_test_asserts_thresholds
  - default_thresholds_length_0_10_embedding_0_10_judge_0_10
  - html_report_is_single_file_inline_svg_no_external_cdn_pattern_matches_rag_kit_telemetry_dashboard
decisions_made: [D-014]
followups: []
---

---
session: 2026-05-18T15:30Z
duration_min: 30
issue: 15
focus: run_tags_filter_set_union_subset_eval
delta:
  files_added: 1   # tests/test_tag_filter.py
  files_changed: 5  # dataset.py, runner.py, cli.py, test_cli_run.py, README.md
  tests_added: 11  # 7 helper + 4 CLI
  test_pass_rate: "137/137"
context_for_next_session:
  - filter_examples_by_tags_and_collect_tag_inventory_live_in_dataset_py_set_union_semantics_pure_no_runner_deps
  - empty_tag_filter_error_in_runner_py_carries_requested_tags_and_inventory_so_silent_zero_rows_is_impossible
  - parse_tags_arg_in_cli_treats_whitespace_only_string_as_no_filter_degenerate_input_must_not_silently_match_zero
  - run_spec_tags_field_default_empty_tuple_no_filter_behavior_unchanged_when_flag_absent
  - calibrate_was_excluded_from_tag_filter_intentionally_calibration_row_schema_has_no_tags_field
  - cli_exit_2_on_unknown_tag_distinct_from_exit_1_regression_flag_and_exit_0_clean_run
issue_15_closure_after_pr_16_merge: true
decisions_made: []
followups: []
---

---
session: 2026-05-18T19:30Z
duration_min: 45
issue: 17
focus: examples_directory_runnable_hermetic_with_smoke_test
delta:
  files_added: 6   # 4 examples + examples/__init__.py + tests/test_examples_smoke.py
  files_changed: 1  # README.md gets ### Examples subsection + drops stale 68-tests number
  tests_added: 8   # smoke tests
  test_pass_rate: "145/145"
context_for_next_session:
  - examples_dir_has_four_files_judge_calibration_stub_regression_run_and_diff_drift_report_pytest_eval
  - every_example_exposes_main_int_with_name_main_guard_so_smoke_test_can_call_main_uniformly
  - pytest_eval_example_main_shells_out_to_pytest_subprocess_to_keep_outer_and_inner_suites_isolated
  - smoke_test_imports_each_example_fresh_via_importlib_then_redirects_stdout_to_assert_sentinels
  - regression_example_uses_tempdir_sqlite_so_repeated_runs_do_not_pollute_user_home
  - drift_example_uses_tempfile_namedtemporaryfile_delete_false_so_smoke_test_can_assert_html_contents
  - readme_examples_subsection_under_quickstart_complements_library_use_snippet_does_not_replace_it
  - readme_test_count_changed_from_specific_68_to_generic_full_hermetic_suite_to_avoid_bitrot
decisions_made: []
followups: []
---

---
session: 2026-05-19T04:45Z
duration_min: 45
issue: 19
focus: readme_drop_session_specific_framing_plus_snapshot_test
delta:
  files_changed: 1   # README.md
  files_added: 1     # tests/test_readme_snapshot.py
  tests_added: 4
  test_pass_rate: "149/149"
context_for_next_session:
  - readme_what_this_is_rewritten_to_nine_bullet_landing_order_drops_three_pieces_shipped_today
  - architecture_mermaid_now_shows_all_shipped_pieces_and_wiring_including_sticky_comment_pytest_plugin_examples
  - cli_bullet_locked_to_python_m_help_subcommand_surface_via_snapshot
  - demo_section_replaces_pending_until_3_lands_with_two_command_hermetic_demo_path
  - capture_followup_filed_as_issue_20
  - sister_to_eight_other_portfolio_snapshot_prs_landed_today_or_yesterday_pattern_complete_for_now
  - tamper_verified_calibrate_to_nonexistent_in_cli_bullet_fires_snapshot
decisions_made: []
followups: ["#20"]
---

---
session: 2026-05-19T19:30Z
duration_min: 35
issue: 22
focus: snapshot_lock_readme_numeric_identifier_defaults_to_source
delta:
  files_added: 1   # tests/test_readme_defaults_snapshot.py
  tests_added: 6
  test_pass_rate: "155/155"
context_for_next_session:
  - readme_defaults_now_locked_six_pairings_calibration_rows_pip_extras_threshold_drop_kappa_gate_cluster_k_sticky_marker
  - kappa_default_parsed_by_regex_against_cli_py_argparse_no_clean_introspection_for_subparser_defaults
  - tamper_verified_three_of_six_threshold_drop_calibration_rows_cluster_k
  - sister_to_existing_test_readme_snapshot_py_orthogonal_axis_numeric_not_structural
decisions_made: []
followups: []
---

---
session: 2026-05-19T20:30Z
duration_min: 30
issue: 24
focus: public_surface_snapshot_locks_eval_harness_top_level_init_exports
delta:
  files_added: 1   # tests/test_public_surface.py
  files_changed: 1 # .gitignore (added .coverage artifacts)
  tests_added: 10
  test_pass_rate: "165/165"
  coverage_init_py: "0pct_to_100pct"
context_for_next_session:
  - public_surface_snapshot_five_axes_version_all_bound_all_matches_imports_readme_example_imports_submodule_anchors
  - importlib_reload_at_module_top_works_around_entry_points_plugin_loading_before_pytest_cov_instruments_otherwise_init_py_stays_at_zero_coverage
  - ast_parses_init_py_to_extract_actual_top_level_import_block_compared_against_all_in_both_directions
  - parametrized_over_six_submodules_judge_calibration_dataset_drift_runner_runs_one_anchor_each
  - tamper_verified_three_of_five_drop_all_entry_alias_rename_re_import_garbage_version
  - sister_to_existing_test_readme_snapshot_py_and_test_readme_defaults_snapshot_py_orthogonal_axis_python_surface_vs_readme_text
  - filed_issue_24_in_session_when_loop_started_no_priority_high_or_med_open_in_any_portfolio_repo_falls_under_self_filed_actionable_per_phase_b_step_5_escape
decisions_made: []
followups: []
---

---
session: 2026-05-22T03:55Z
duration_min: 25
issue: 27
focus: hide_judge_calibrate_alias_from_top_level_help_keep_alias_working
decisions_made: []
delta:
  files_changed: 2  # eval_harness/cli.py, README.md
  files_added: 1    # tests/test_cli_judge_alias.py
  tests_added: 4
  test_pass_rate: "169/169"
context_for_next_session:
  - judge_p_subparser_was_registered_with_visible_help_string_so_eval_harness_help_showed_judge_judge_related_subcommands_contradicting_module_docstring_hidden_nested_alias_claim
  - argparse_subparser_help_suppress_renders_as_literal_suppress_string_not_truly_hidden_so_chose_argv_rewrite_approach_in_main
  - if_argv_starts_with_judge_calibrate_rewrite_to_calibrate_before_argparse_parses_so_judge_subparser_doesnt_register_at_all
  - alias_via_alias_help_byte_identical_to_via_canonical_help_pinned_in_test
  - bare_eval_harness_judge_and_eval_harness_judge_unknown_subcommand_fail_correctly_at_parser_level_pinned_in_test
  - readme_l100_quickstart_uses_canonical_calibrate_with_one_paragraph_explaining_legacy_alias_still_works
  - readme_l317_benchmarks_pending_line_uses_canonical_calibrate
  - seventh_post_v0_1_drift_fix_today
followups: []
---

---
session: 2026-05-22T19:50Z
duration_min: 30
issue: 29
focus: docs_architecture_md_reflects_all_nine_shipped_surfaces_not_one_plus_two_only_pre_shipping_state
delta:
  files_changed: 1   # docs/architecture.md
  files_added: 1     # tests/test_architecture_doc.py
  tests_added: 7
  tamper_verify_axes: 3
context_for_next_session:
  - architecture_md_was_frozen_at_judge_calibration_pr_issue_2_directory_diagram_5_modules_reality_10_modules_pending_downstream_section_listed_3_4_5_6_7_as_future_work_all_closed
  - rewrote_to_full_10_module_directory_diagram_plus_per_layer_sections_for_3_4_5_6_plus_cli_surface_section_plus_cross_cutting_surfaces_section_15_17_24_19_22
  - new_tests_test_architecture_doc_py_three_invariants_with_star_added_to_placeholder_skip_for_tests_test_cli_pattern_eval_harness_specific
  - known_shipped_issues_1_2_3_4_5_6_7_15_17_excluded_19_20_22_24_27_each_locked_separately_by_own_dedicated_snapshot_regression_test
  - banned_phrases_this_pr_pending_downstream_unfiled_to_be_filed
  - tamper_verified_three_axes_each_fires_with_specific_drift_quoted
  - fourteenth_post_v0_1_drift_or_doc_fix_in_portfolio_pattern_fifth_architecture_doc_lock_test_in_this_session_after_mcp_cookbook_emb_shootout_vss_nextjs_ai_app
  - portfolio_now_eight_repos_with_architecture_doc_lock_tests
  - issue_filed_mid_session_as_priority_med_then_closed_in_same_session_per_session_prompt_loop_protocol
  - first_repo_in_build_sequence_eval_harness_was_natural_next_target_after_emb_shootout_pos_5_and_vss_pos_7
decisions_made: []
followups: []
---
