# Recorded-run remediation (suite 5.0.1)

The 200-scenario recording and its accompanying suite 5.0.0 report exposed both application defects and test defects. The report contains 95 data-check failures: 93 have correct primary-result checks but failing supporting evidence, and two fail their row-result digest. It does not demonstrate 95 arithmetic errors. Raw records and the user's report are not included in the repository.

## Changes

- SQL Decimal values serialize in fixed notation. Typed numeric digests also accept scientific notation, including scaled zero (`0E-10`). Previously the production digest could hash that zero as text while the reference hashed it as a number; cell-by-cell comparisons and totals could agree while digests failed. Text identifiers remain text. No amounts, tolerances, source mappings or business definitions were changed.
- Aggregate results return all groups unless the question specifies a limit. Ordinary row results retain their 1,000-row preview. Saved aggregate results retain the complete groups too, subject to the existing compressed-answer byte limit. Date charts, Data, local measure switches and CSV now receive the same complete aggregate result. Existing incomplete saved answers require an explicit rerun to obtain omitted data.
- Date-axis titles have room above the plot; numeric ticks hide overlaps and horizontal charts use fewer tick divisions. Scalar quantities use thousands separators without discarding fractional precision.
- Planner guidance gives explicitly named date fields precedence over the topic's default closing month, preserves sort on limit-only refinements, and distinguishes whole-opportunity scope from product-only scope regardless of the selected measure. Five continuity scenarios now explicitly say “close date”; their former “closing in 2026” wording conflicted with the documented default closing-month rule. This is a clarified test contract, not evidence that the model's previous default-month interpretation was wrong.
- Known shipped business-rule defaults migrate to the clarified date wording; custom rules remain protected by whole-file hash matching.
- A data-check failure with a valid interpreted plan does not block later turns. Unexpected clarification, request failure and invalid context still block dependent turns. Authored independent resets run in the same conversation to test actual recovery. Failed turns continue to prevent full-pass qualification.
- The live toolbar includes review counts and expandable, separate interpretation, primary-result and supporting-record verdicts. Copied review batches now include supporting-view checks and exact differences, which were previously omitted.
- Browser checks restart pagination before each complete read and dismiss menus through the focused control. Resize checks compare the SVG with its actual chart host instead of assuming the surrounding app shell scales linearly.

## Validation and limits

Local validation: 261 backend tests run (eight skipped, no failures/errors); 34 frontend tests passed; 20 desktop browser regressions passed; 19 phone regressions passed (two desktop-only skips). Three targeted desktop tests also passed after the final UI build, including the new complete-date-chart test, live PNG retries, and all sixteen synthetic browser checks. Type checking, the production build, and the compiled-source fingerprint check passed. The scaled-zero fixture reproduces digest-only failures in both supporting views with the previous code and passes with the correction.

Regression fixtures cover SQL scaled zero, detection of changed supporting cells, numeric/text identifier separation, complete 1,011-group date results, explicit query limits, saved aggregate retention, quantity formatting, differing close-date and close-month populations, continuing after data failures, and recovering after context errors. A browser regression verifies the final date group beyond 1,000, CSV completeness and Chart/Data switching.

The suite still contains 200 scenarios and 291 turns. Tests are initiated explicitly; these changes do not run the suite at startup or installation. Recording remains local to the capture PC.

This implementation has not been run against the work PC's retained live snapshot or local Qwen model. The scaled-zero failure mechanism is reproduced with independent fixtures; a replay of that retained snapshot is still needed to establish how many historical failures it resolves. Source amount/currency semantics remain subject to the existing independent source-contract qualification. Prompt improvements require a live model retest. No historical verdict is rewritten as a pass.
