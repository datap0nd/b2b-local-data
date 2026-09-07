-- Based on the supplied replication manual. Run manually with a migration role.
-- Invalid dates become NULL; C collation keeps text min/ordering equal to Python.
BEGIN;

-- 1. Schema versioning table
CREATE TABLE IF NOT EXISTS bi_reporting.b2b_project_schema_version (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- 2. SKU Grain View
CREATE OR REPLACE VIEW bi_reporting.b2b_project_sku_v AS
WITH normalized AS (
    SELECT
        NULLIF(btrim(opportunity_no), '') COLLATE "C" AS opportunity_no,
        NULLIF(btrim(product_code), '') COLLATE "C" AS product_code,
        NULLIF(btrim(subsidiary_subsidiary_code), '') COLLATE "C" AS subsidiary_subsidiary_code,
        NULLIF(btrim(opportunity_name), '') COLLATE "C" AS opportunity_name,
        NULLIF(btrim(end_customer), '') COLLATE "C" AS end_customer,
        NULLIF(btrim(gscm_product_group_new), '') COLLATE "C" AS gscm_product_group_new,
        NULLIF(btrim(pet_name), '') COLLATE "C" AS pet_name,
        NULLIF(btrim(stage), '') COLLATE "C" AS stage,
        NULLIF(btrim(opportunity_owner), '') COLLATE "C" AS opportunity_owner,
        NULLIF(btrim(biz_focus), '') COLLATE "C" AS biz_focus,
        NULLIF(btrim(business_location), '') COLLATE "C" AS business_location,
        NULLIF(btrim(division), '') COLLATE "C" AS division,
        NULLIF(btrim(sales_type_detail), '') COLLATE "C" AS sales_type_detail,
        NULLIF(btrim(type), '') COLLATE "C" AS type,
        NULLIF(btrim(amount_converted_currency), '') COLLATE "C" AS amount_converted_currency,
        NULLIF(btrim(opp_amount_converted_currency), '') COLLATE "C" AS opp_amount_converted_currency,
        CASE WHEN btrim(quantity) ~ '^[+-]?[0-9]+([.][0-9]+)?$'
             THEN btrim(quantity)::numeric END AS quantity,
        CASE WHEN btrim(amount_converted) ~ '^[+-]?[0-9]+([.][0-9]+)?$'
             THEN btrim(amount_converted)::numeric END AS amount_converted,
        CASE WHEN btrim(opp_amount_converted) ~ '^[+-]?[0-9]+([.][0-9]+)?$'
             THEN btrim(opp_amount_converted)::numeric END AS exported_opp_amount,
        CASE WHEN btrim(probability) ~ '^[0-9]+([.][0-9]+)?%?$'
             THEN replace(btrim(probability), '%', '')::numeric / 100 END AS probability,
        CASE WHEN NULLIF(btrim(close_month), '') ~ '^(0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/[0-9]{4}$'
             THEN CASE WHEN substring(NULLIF(btrim(close_month), '') from 7 for 4)::integer BETWEEN 1 AND 9999
                  THEN CASE WHEN substring(NULLIF(btrim(close_month), '') from 1 for 2)::integer <= extract(day from (make_date(substring(NULLIF(btrim(close_month), '') from 7 for 4)::integer, substring(NULLIF(btrim(close_month), '') from 4 for 2)::integer, 1) + interval '1 month - 1 day'))
                       THEN make_date(substring(NULLIF(btrim(close_month), '') from 7 for 4)::integer, substring(NULLIF(btrim(close_month), '') from 4 for 2)::integer, substring(NULLIF(btrim(close_month), '') from 1 for 2)::integer) END END END AS close_month,
        CASE WHEN NULLIF(btrim(close_date), '') ~ '^(0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/[0-9]{4}$'
             THEN CASE WHEN substring(NULLIF(btrim(close_date), '') from 7 for 4)::integer BETWEEN 1 AND 9999
                  THEN CASE WHEN substring(NULLIF(btrim(close_date), '') from 1 for 2)::integer <= extract(day from (make_date(substring(NULLIF(btrim(close_date), '') from 7 for 4)::integer, substring(NULLIF(btrim(close_date), '') from 4 for 2)::integer, 1) + interval '1 month - 1 day'))
                       THEN make_date(substring(NULLIF(btrim(close_date), '') from 7 for 4)::integer, substring(NULLIF(btrim(close_date), '') from 4 for 2)::integer, substring(NULLIF(btrim(close_date), '') from 1 for 2)::integer) END END END AS close_date,
        CASE WHEN NULLIF(btrim(created_date), '') ~ '^(0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/[0-9]{4}$'
             THEN CASE WHEN substring(NULLIF(btrim(created_date), '') from 7 for 4)::integer BETWEEN 1 AND 9999
                  THEN CASE WHEN substring(NULLIF(btrim(created_date), '') from 1 for 2)::integer <= extract(day from (make_date(substring(NULLIF(btrim(created_date), '') from 7 for 4)::integer, substring(NULLIF(btrim(created_date), '') from 4 for 2)::integer, 1) + interval '1 month - 1 day'))
                       THEN make_date(substring(NULLIF(btrim(created_date), '') from 7 for 4)::integer, substring(NULLIF(btrim(created_date), '') from 4 for 2)::integer, substring(NULLIF(btrim(created_date), '') from 1 for 2)::integer) END END END AS created_date,
        CASE WHEN NULLIF(btrim(last_modified_date), '') ~ '^(0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/[0-9]{4}$'
             THEN CASE WHEN substring(NULLIF(btrim(last_modified_date), '') from 7 for 4)::integer BETWEEN 1 AND 9999
                  THEN CASE WHEN substring(NULLIF(btrim(last_modified_date), '') from 1 for 2)::integer <= extract(day from (make_date(substring(NULLIF(btrim(last_modified_date), '') from 7 for 4)::integer, substring(NULLIF(btrim(last_modified_date), '') from 4 for 2)::integer, 1) + interval '1 month - 1 day'))
                       THEN make_date(substring(NULLIF(btrim(last_modified_date), '') from 7 for 4)::integer, substring(NULLIF(btrim(last_modified_date), '') from 4 for 2)::integer, substring(NULLIF(btrim(last_modified_date), '') from 1 for 2)::integer) END END END AS last_modified_date,
        NULLIF(btrim(rollout_period_to), '') COLLATE "C" AS rollout_period_to,
        NULLIF(btrim(rollout_period_from), '') COLLATE "C" AS rollout_period_from
    FROM bi_reporting.b2b_project
)
SELECT
    opportunity_no,
    product_code,
    min(subsidiary_subsidiary_code) AS subsidiary_subsidiary_code,
    min(opportunity_name) AS opportunity_name,
    min(end_customer) AS end_customer,
    min(gscm_product_group_new) AS gscm_product_group_new,
    min(pet_name) AS pet_name,
    min(stage) AS stage,
    min(opportunity_owner) AS opportunity_owner,
    min(biz_focus) AS biz_focus,
    min(business_location) AS business_location,
    min(division) AS division,
    min(sales_type_detail) AS sales_type_detail,
    min(type) AS type,
    min(amount_converted_currency) AS amount_converted_currency,
    min(opp_amount_converted_currency) AS opp_amount_converted_currency,
    sum(quantity) AS quantity,
    sum(amount_converted) AS sku_amount,
    min(exported_opp_amount) AS exported_opp_amount_min,
    max(exported_opp_amount) AS exported_opp_amount_max,
    count(DISTINCT exported_opp_amount) AS exported_opp_amount_value_count,
    min(probability) AS probability,
    min(close_month) AS close_month,
    min(close_date) AS close_date,
    min(created_date) AS created_date,
    max(last_modified_date) AS last_modified_date,
    min(rollout_period_to) AS rollout_period_to,
    min(rollout_period_from) AS rollout_period_from,
    count(*)::integer AS source_row_count,
    (
        count(DISTINCT exported_opp_amount) > 1
        OR count(DISTINCT opportunity_name) > 1
        OR count(DISTINCT end_customer) > 1
        OR count(DISTINCT pet_name) > 1
        OR count(DISTINCT gscm_product_group_new) > 1
        OR count(DISTINCT stage) > 1
        OR count(DISTINCT opportunity_owner) > 1
        OR count(DISTINCT amount_converted_currency) > 1
    ) AS has_quality_warning
FROM normalized
WHERE opportunity_no IS NOT NULL AND product_code IS NOT NULL
GROUP BY opportunity_no, product_code;

-- 3. Opportunity Grain View
CREATE OR REPLACE VIEW bi_reporting.b2b_project_opportunity_v AS
SELECT
    opportunity_no,
    min(subsidiary_subsidiary_code) AS subsidiary_subsidiary_code,
    min(opportunity_name) AS opportunity_name,
    min(end_customer) AS end_customer,
    min(stage) AS stage,
    min(opportunity_owner) AS opportunity_owner,
    min(biz_focus) AS biz_focus,
    min(business_location) AS business_location,
    min(division) AS division,
    min(sales_type_detail) AS sales_type_detail,
    min(type) AS type,
    min(opp_amount_converted_currency) AS opp_amount_converted_currency,
    min(probability) AS probability,
    min(close_month) AS close_month,
    min(close_date) AS close_date,
    min(created_date) AS created_date,
    max(last_modified_date) AS last_modified_date,
    min(rollout_period_to) AS rollout_period_to,
    min(rollout_period_from) AS rollout_period_from,
    sum(quantity) AS quantity,
    sum(sku_amount) AS opportunity_amount,
    count(*)::integer AS sku_count,
    sum(source_row_count)::integer AS source_row_count,
    string_agg(DISTINCT product_code, ', ' ORDER BY product_code) AS product_codes,
    string_agg(DISTINCT pet_name, ', ' ORDER BY pet_name) AS product_names,
    min(exported_opp_amount_min) AS exported_opp_amount_min,
    max(exported_opp_amount_max) AS exported_opp_amount_max,
    COALESCE(NOT (
        min(exported_opp_amount_min) = max(exported_opp_amount_max)
        AND abs(sum(sku_amount) - max(exported_opp_amount_max)) <= 0.01
    ), true) AS has_amount_discrepancy,
    bool_or(has_quality_warning) OR COALESCE(NOT (
        min(exported_opp_amount_min) = max(exported_opp_amount_max)
        AND abs(sum(sku_amount) - max(exported_opp_amount_max)) <= 0.01
    ), true) AS has_quality_warning
FROM bi_reporting.b2b_project_sku_v
GROUP BY opportunity_no;

INSERT INTO bi_reporting.b2b_project_schema_version(version)
VALUES (1)
ON CONFLICT (version) DO UPDATE SET applied_at = now();

COMMIT;
