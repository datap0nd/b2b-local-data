# Product classifications

The PostgreSQL source is `bi_reporting.b2b_project_segmented`. Its upstream join
on `pet_name` adds `biz_group`, `seg_1`, `seg_2`, `seg_3`, and `series` to each source
line. The application reads this materialized view; it does not create or refresh it.

The classification order is business group → segment 1 → segment 2 → segment 3 →
series, followed by the individual products. The existing `division` and
`gscm_product_group_new` fields remain separate attributes. All five classifications
support product-row columns, filters, grouping, charts, and supporting records.

Examples supplied by the user include SMART, FEATURE, ACCESSORY, TABLET and
WEARABLE business groups; FLAGSHIP and A SERIES in segment 1; ENTRY, MID, HIGH,
S, TABL_ENTRY and TAB_MASS in segment 2; A0x and A1x in segment 3; and A SERIES CASE
or A0x in series. These are vocabulary examples, not an asserted inventory.
Equality and membership filters are case-insensitive for these five fields;
displayed labels retain the source spelling and punctuation.

“Current-generation flagship” maps to `seg_3 = S(N)` and “previous-generation
flagship” to `seg_3 = S(N-1)`. These are literal labels, not dates or arithmetic.
“By segment” without a level requires clarification. “Smart products” maps to
`biz_group = SMART`.

Product breakdowns use the opportunity/product grain. Whole opportunities
containing a classified product include their other products too; quantities and
amounts for matching products include only those products. Distinct opportunity
counts can overlap across classification groups. Whole-opportunity deal size
cannot be broken down by product classification because that repeats the total.

Suite 5 adds classification coverage within the existing 200 scenarios and 291
turns. It checks authored interpretation, rendering, and arithmetic relative to
the snapshot. Values for generic classification filters are selected deterministically
from the snapshot. Missing prerequisites are unavailable, never passes. Synthetic
regressions exercise mixed classifications, case, generation labels, follow-ups,
fingerprints, legacy CSV compatibility, and materialized-view discovery.

No tests qualify the actual upstream join or classification assignments without
the updated data. In particular, arithmetic over the materialized view cannot prove
that its `pet_name` join has not multiplied source lines. Source-owner validation
of join cardinality and category mappings remains separate from these behavior tests.
