# Product scope clarification

Short marketing names can refer to a base model or multiple variants. Previously the planner's generic contains rule could include Plus, Ultra, FE and accessories, while an exact list of shortened names could return no matches.

The planner now asks about ambiguous scope and preserves the pending question and existing filters through clarification. Before execution, a snapshot-based resolver checks new pet_name restrictions. It asks about multiple matches rather than silently expanding a name, resolves unique whole-word suffix aliases in explicit lists to stored names, and refuses to guess between brands sharing an alias. It does not contain a particular generation's product map. Explicit literal substring searches retain contains behavior. Product codes and classification filters are unchanged.

An exact base-model choice uses equality; explicit lists include only their named members. A generated clarification is saved as a clarification turn without executing a query or replacing the active plan. The original request remains in conversation history for the model to finish. Existing shipped rule defaults migrate by their recorded whole-file hashes; custom rule files are preserved, with the runtime product-scope policy taking precedence over the former generic contains guidance.

Regressions use invented Orbit Q7 and Nova Q7 products. They cover ambiguity, exact lists, FE/accessory exclusion, shared aliases, base-only amount within a mixed-product BO, explicit substring queries, negative wording, and stage/date context preservation. Local-model language behavior still needs a work-PC retest after updating.
