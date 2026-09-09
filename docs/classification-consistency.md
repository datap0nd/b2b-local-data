# Enforced B2B classification scope

`config/b2b_classifications.json` owns the supported topic definitions. The model prompt and pre-execution resolver read the same definitions, so prompt fingerprints also cover vocabulary changes.

- Bare flagship uses Segment 1 = FLAGSHIP, with no inferred generation filter.
- Current-generation flagship uses Segment 3 = S(N).
- Previous-generation flagship uses Segment 3 = S(N-1).

The resolver replaces conflicting Segment 1/3 restrictions when one of these scopes is explicitly named. Unrelated filters, product scope, measures, sorting, limits and grouping remain intact. Ordinary follow-ups retain confirmed scope. Negations, removal requests, mixed generation requests, named-entity collisions and unclear extra classification wording ask for clarification instead of executing a guessed scope. Model clarifications remain clarifications.

Diagnostics record whether enforcement changed the plan. The original model plan remains available as `returned_plan`; the executed plan and saved conversation contain the enforced filters. Clarifications do not overwrite the last executed plan.

Existing top-opportunity ranking and default closing-period rules remain unchanged. This change does not promise identical answers across different snapshots, conversation histories, model versions or other interpretations. It enforces these classification definitions; it does not infer missing source classifications or certify live-source business definitions.

Synthetic tests intentionally inject single-generation, two-generation and missing filters. They verify convergence, inclusion of older flagship generations, exclusion of nonflagship products, explicit generations, ambiguity handling and saved-context isolation. Real-data counts still need work-PC verification.
