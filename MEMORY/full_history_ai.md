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
