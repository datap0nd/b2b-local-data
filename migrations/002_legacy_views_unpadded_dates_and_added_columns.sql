-- LEGACY VIEW REFRESH. The application (0.4.0 and later) reads the raw table directly and does not
-- depend on these views or on the version ledger; the read-only application role needs no DDL.
-- Apply this only if other consumers still use the derived views, so that they agree with the app:
--   * day-first dates accept one- or two-digit day and month (e.g. 1/12/2022), ISO YYYY-MM-DD text is accepted
--     as well (typed date columns rendered as text), and invalid dates stay NULL;
--   * the four columns added later (1st_channel, age, comment, deal_size_on_pricing_date_usd) are exposed
--     as opportunity attributes selected with MIN, never summed, and counted in has_quality_warning.
-- Run manually with a migration-capable role. Requires migration 001 to have been applied first.
BEGIN;

CREATE OR REPLACE FUNCTION bi_reporting.b2b_day_first_date(value text) RETURNS date
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE trimmed text := btrim(value); parts text[];
BEGIN
    -- ISO text (YYYY-MM-DD, optionally followed by a time) is accepted exactly like the application, which
    -- receives typed date/timestamp columns cast to text; anything else must be day-first D/M/YYYY.
    IF trimmed ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T][0-9:.+-]*Z?)?$' THEN
        BEGIN
            RETURN make_date(substr(trimmed, 1, 4)::integer, substr(trimmed, 6, 2)::integer, substr(trimmed, 9, 2)::integer);
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
    END IF;
    IF trimmed !~ '^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}$' THEN RETURN NULL; END IF;
    parts := string_to_array(trimmed, '/');
    BEGIN
        RETURN make_date(parts[3]::integer, parts[2]::integer, parts[1]::integer);
    EXCEPTION WHEN OTHERS THEN
        RETURN NULL;
    END;
END $$;

DROP VIEW IF EXISTS bi_reporting.b2b_project_opportunity_v;
DROP VIEW IF EXISTS bi_reporting.b2b_project_sku_v;

CREATE VIEW bi_reporting.b2b_project_sku_v AS
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
        NULLIF(btrim(rollout_period_to), '') COLLATE "C" AS rollout_period_to,
        NULLIF(btrim(rollout_period_from), '') COLLATE "C" AS rollout_period_from,
        NULLIF(btrim("1st_channel"), '') COLLATE "C" AS first_channel,
        NULLIF(btrim(comment), '') COLLATE "C" AS comment,
        CASE WHEN btrim(quantity) ~ '^[+-]?[0-9]+([.][0-9]+)?$' THEN btrim(quantity)::numeric END AS quantity,
        CASE WHEN btrim(amount_converted) ~ '^[+-]?[0-9]+([.][0-9]+)?$' THEN btrim(amount_converted)::numeric END AS amount_converted,
        CASE WHEN btrim(opp_amount_converted) ~ '^[+-]?[0-9]+([.][0-9]+)?$' THEN btrim(opp_amount_converted)::numeric END AS exported_opp_amount,
        CASE WHEN btrim(probability) ~ '^[0-9]+([.][0-9]+)?%?$' THEN replace(btrim(probability), '%', '')::numeric / 100 END AS probability,
        CASE WHEN btrim(age) ~ '^[+-]?[0-9]+([.][0-9]+)?$' THEN btrim(age)::numeric END AS age,
        CASE WHEN btrim(deal_size_on_pricing_date_usd) ~ '^[+-]?[0-9]+([.][0-9]+)?$' THEN btrim(deal_size_on_pricing_date_usd)::numeric END AS deal_size_on_pricing_date_usd,
        bi_reporting.b2b_day_first_date(close_month) AS close_month,
        bi_reporting.b2b_day_first_date(close_date) AS close_date,
        bi_reporting.b2b_day_first_date(created_date) AS created_date,
        bi_reporting.b2b_day_first_date(last_modified_date) AS last_modified_date
    FROM bi_reporting.b2b_project
)
SELECT
    opportunity_no, product_code,
    min(subsidiary_subsidiary_code) AS subsidiary_subsidiary_code, min(opportunity_name) AS opportunity_name, min(end_customer) AS end_customer,
    min(gscm_product_group_new) AS gscm_product_group_new, min(pet_name) AS pet_name, min(stage) AS stage, min(opportunity_owner) AS opportunity_owner,
    min(biz_focus) AS biz_focus, min(business_location) AS business_location, min(division) AS division, min(sales_type_detail) AS sales_type_detail,
    min(type) AS type, min(amount_converted_currency) AS amount_converted_currency, min(opp_amount_converted_currency) AS opp_amount_converted_currency,
    min(rollout_period_to) AS rollout_period_to, min(rollout_period_from) AS rollout_period_from, min(first_channel) AS first_channel, min(comment) AS comment,
    sum(quantity) AS quantity, sum(amount_converted) AS sku_amount,
    min(exported_opp_amount) AS exported_opp_amount_min, max(exported_opp_amount) AS exported_opp_amount_max,
    count(DISTINCT exported_opp_amount) AS exported_opp_amount_value_count, min(probability) AS probability,
    min(age) AS age, min(deal_size_on_pricing_date_usd) AS deal_size_on_pricing_date_usd,
    min(close_month) AS close_month, min(close_date) AS close_date, min(created_date) AS created_date, max(last_modified_date) AS last_modified_date,
    count(*)::integer AS source_row_count,
    (count(DISTINCT exported_opp_amount) > 1 OR count(DISTINCT opportunity_name) > 1 OR count(DISTINCT end_customer) > 1 OR count(DISTINCT pet_name) > 1
     OR count(DISTINCT gscm_product_group_new) > 1 OR count(DISTINCT stage) > 1 OR count(DISTINCT opportunity_owner) > 1 OR count(DISTINCT amount_converted_currency) > 1
     OR count(DISTINCT first_channel) > 1 OR count(DISTINCT age) > 1 OR count(DISTINCT comment) > 1 OR count(DISTINCT deal_size_on_pricing_date_usd) > 1) AS has_quality_warning
FROM normalized
WHERE opportunity_no IS NOT NULL AND product_code IS NOT NULL
GROUP BY opportunity_no, product_code;

CREATE VIEW bi_reporting.b2b_project_opportunity_v AS
SELECT
    opportunity_no,
    min(subsidiary_subsidiary_code) AS subsidiary_subsidiary_code, min(opportunity_name) AS opportunity_name, min(end_customer) AS end_customer,
    min(stage) AS stage, min(opportunity_owner) AS opportunity_owner, min(biz_focus) AS biz_focus, min(business_location) AS business_location,
    min(division) AS division, min(sales_type_detail) AS sales_type_detail, min(type) AS type, min(opp_amount_converted_currency) AS opp_amount_converted_currency,
    min(rollout_period_to) AS rollout_period_to, min(rollout_period_from) AS rollout_period_from, min(first_channel) AS first_channel, min(comment) AS comment,
    min(probability) AS probability, min(age) AS age, min(deal_size_on_pricing_date_usd) AS deal_size_on_pricing_date_usd,
    min(close_month) AS close_month, min(close_date) AS close_date, min(created_date) AS created_date, max(last_modified_date) AS last_modified_date,
    sum(quantity) AS quantity, sum(sku_amount) AS opportunity_amount, count(*)::integer AS sku_count, sum(source_row_count)::integer AS source_row_count,
    string_agg(DISTINCT product_code, ', ' ORDER BY product_code) AS product_codes, string_agg(DISTINCT pet_name, ', ' ORDER BY pet_name) AS product_names,
    min(exported_opp_amount_min) AS exported_opp_amount_min, max(exported_opp_amount_max) AS exported_opp_amount_max,
    COALESCE(NOT (min(exported_opp_amount_min) = max(exported_opp_amount_max) AND abs(sum(sku_amount) - max(exported_opp_amount_max)) <= 0.01), true) AS has_amount_discrepancy,
    bool_or(has_quality_warning)
      OR COALESCE(NOT (min(exported_opp_amount_min) = max(exported_opp_amount_max) AND abs(sum(sku_amount) - max(exported_opp_amount_max)) <= 0.01), true)
      OR count(DISTINCT first_channel) > 1 OR count(DISTINCT age) > 1 OR count(DISTINCT comment) > 1 OR count(DISTINCT deal_size_on_pricing_date_usd) > 1 AS has_quality_warning
FROM bi_reporting.b2b_project_sku_v
GROUP BY opportunity_no;

INSERT INTO bi_reporting.b2b_project_schema_version(version) VALUES (2)
ON CONFLICT (version) DO UPDATE SET applied_at = now();

COMMIT;
