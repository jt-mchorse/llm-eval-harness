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
