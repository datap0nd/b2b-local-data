# Live tests and recording: two separate PCs

## On this local capture PC

Run `capture.ps1` from this project. It starts a loopback-only viewer and opens it
in Chrome. Choose **Connect feed**, then **Start recording**. The only accepted
video device is `UGREEN-25854`, optionally followed by its hardware suffix.
Camera permission is required; microphone permission is never requested.

The toolbar displays the actual resolution and recording time. **Stop & save**
finishes a WebM in this PC's `test-results/recordings/<recording-id>/capture.webm`.
Keep the launcher and Chrome page open while recording. Nothing is uploaded.
The viewer cannot send keyboard or mouse input to the work PC.

Each recording retains ordered chunks and a manifest. If the page or device is
interrupted, reopen the viewer and choose **Recover** for the interrupted recording.
Recovery assembles only chunks that reached local disk. It cannot recover frames
that were never captured or transmitted to the local recorder process. The viewer
stops recording if disk writes cannot keep up and reports errors explicitly.

The assistant can inspect fresh frames during an active task, then use this local
recording to revisit missed moments. This is sampled inspection, not guaranteed
continuous perception. Scenario/turn labels identify frames without matching clocks
between PCs.

## On the work PC running B2B

Installation, updates, and normal startup never run the test suite or generate test
images. Installation validates release files, dependencies, and configuration only.
Tests start when you choose **Test → Run tests**.

Open **Test → Run tests**. The suite contains 200 scenarios and 291 prompt turns,
including 40 continuity scenarios. It calls the configured local model and captures
one fresh source snapshot for the entire run. There is no duration limit.

The normal conversation, chart, table, composer and expanded-result components show
each turn. Test sessions live in the separate acceptance store and never appear in
normal saved chats. **Pause** stops advancing between actions; **Stop** waits for
the in-flight model request, then cancels the remaining run. The default display hold
is two seconds after each completed response/action. Set it before starting.

The Test panel retains its run ID separately from the normal conversation. After a
browser reload, reopen Test and choose **Resume run**. Completed model calls are
reused. A backend restart interrupts the snapshot run; its evidence remains available,
but a new live run is required.

Each scenario produces one numbered PNG containing its prompts, actual rendered
responses, and test observations. These images are generated on the **work PC** in
its installation's `test-results/<run-id>` folder. A complete run requires 200 PNGs
and UI observations. PNG retries do not resubmit model prompts. Individual table
previews are bounded; independent numeric checks cover the full results.

**Copy results for review** provides numbered batches of ten scenarios with a global
summary, interpretations, and exact expected/observed differences. Use this to convey
accuracy evidence when work-PC files cannot be transferred. The Markdown report and
JSON manifest are retained alongside completed images. Partial run reports remain
downloadable from Test.

## What a pass establishes

Interpretation, calculation, rendering checks and human visual review are distinct.
Blocked and unavailable cases are not passes. New unsupported-calculation responses
are marked for semantic review rather than accepted merely because they ask a
clarification. Synthetic checks run separately and never qualify live coverage.

Live PostgreSQL monetary qualification still requires independently verified source
definitions. The reference calculator verifies arithmetic under the documented data
contract; it does not prove upstream Salesforce report semantics.

The capture recording is always made on the **local capture PC**. Only the B2B test
runner and its PNG/report generation run on the work PC.
