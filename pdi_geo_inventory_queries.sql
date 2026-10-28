-- ============================================================================
-- Population Dynamics Insights (PDI) + GA4 + Stock Inventory SQL Pipeline
-- Project: ga4demo-503822
-- Dataset: analytics_312456789
--
-- Summary of Optimizations Applied (per BigQuery SQL Best Practices):
-- 1. Column Pruning: Only required GA4 fields (`user_pseudo_id`, `event_name`,
--    `event_params`, `user_properties`, `geo`, `items`, `ecommerce`, `traffic_source`)
--    and PDI fields (`geo_id`, `geo_name`, `features`, admin Place IDs) are selected.
-- 2. Predicate Pushdown: Event type filters and non-null geographic constraints are
--    pushed into the earliest CTE stages before any UNNEST or spatial joins.
-- 3. Early Aggregation: Hit-level GA4 events are aggregated to `(user_pseudo_id, zcta)`
--    and `(zcta, item_category, item_id)` prior to joining against 330-dim PDI arrays.
-- 4. Common Subexpression Reuse: PDI subspace slices (`vec_search_0_127`,
--    `vec_maps_128_255`, `vec_weather_256_329`), cosine similarities, and Effective
--    Days of Supply (`effective_days_of_supply`) are computed once in dedicated CTEs
--    and referenced downstream without re-evaluating array expressions.
-- 5. Intermediate Materialization: Expensive vector slicing and GA4 ZCTA rollups
--    are materialized as TABLEs (`pdi_zcta_subspaces`, `ga4_zcta_performance`,
--    `geo_expansion_lookalikes`, `stock_aware_routing_decisions`), while lightweight
--    1:1 activation joins use a VIEW (`v_user_geo_stock_activation`).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- STEP 1: Multi-Signal GA4-to-ZCTA (5-Digit ZIP) Geo Resolution & Aggregation
-- Bridges GA4 `events_20*` to 5-digit ZCTAs using:
--   Tier 1: `event_params.zip_code` (store locator / checkout / sGTM IP-to-ZIP)
--   Tier 2: `user_properties.postal_code` (authenticated 1P profile)
--   Tier 3: Deterministic `city_to_zcta_crosswalk` bucketed by `user_pseudo_id`
-- ----------------------------------------------------------------------------
CREATE OR REPLACE TABLE `ga4demo-503822.analytics_312456789.ga4_zcta_performance` AS
WITH pruned_events AS (
  SELECT
    user_pseudo_id,
    event_name,
    event_timestamp,
    geo.city AS geo_city,
    geo.region AS geo_region,
    traffic_source.medium AS traffic_medium,
    CAST(ecommerce.purchase_revenue AS FLOAT64) AS purchase_revenue,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'zip_code') AS param_zip,
    (SELECT value.string_value FROM UNNEST(user_properties) WHERE key = 'postal_code') AS prop_zip,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS session_id,
    items
  FROM
    `ga4demo-503822.analytics_312456789.events_20*`
  WHERE
    geo.country = 'United States'
    AND event_name IN ('page_view', 'view_item', 'add_to_cart', 'begin_checkout', 'purchase')
),

user_resolved_zcta AS (
  SELECT
    e.user_pseudo_id,
    e.event_name,
    e.session_id,
    e.traffic_medium,
    e.purchase_revenue,
    e.items,
    COALESCE(
      e.param_zip,
      e.prop_zip,
      cw.zcta
    ) AS zcta,
    CASE
      WHEN e.param_zip IS NOT NULL THEN 'Tier 1: Event Param (sGTM / Checkout)'
      WHEN e.prop_zip IS NOT NULL THEN 'Tier 2: 1P User Property'
      ELSE 'Tier 3: City-to-ZCTA Crosswalk'
    END AS geo_resolution_tier
  FROM
    pruned_events e
  LEFT JOIN
    `ga4demo-503822.analytics_312456789.city_to_zcta_crosswalk` cw
    ON e.geo_city = cw.city
    AND e.geo_region = cw.region
    AND MOD(ABS(FARM_FINGERPRINT(e.user_pseudo_id)), 100) BETWEEN cw.bucket_start AND cw.bucket_end
),

-- Early aggregation of base ZCTA funnel metrics
zcta_funnel_agg AS (
  SELECT
    zcta,
    ANY_VALUE(geo_resolution_tier) AS primary_resolution_tier,
    COUNT(DISTINCT user_pseudo_id) AS active_users,
    COUNT(DISTINCT session_id) AS total_sessions,
    COUNTIF(traffic_medium IN ('cpc', 'paid', 'ppc', 'display')) AS paid_ad_events,
    COUNT(1) AS total_events,
    COUNTIF(event_name = 'view_item') AS item_views,
    COUNTIF(event_name = 'add_to_cart') AS cart_additions,
    COUNTIF(event_name = 'begin_checkout') AS checkouts,
    COUNTIF(event_name = 'purchase') AS purchases,
    ROUND(SUM(COALESCE(purchase_revenue, 0.0)), 2) AS total_revenue_usd
  FROM
    user_resolved_zcta
  WHERE
    zcta IS NOT NULL
  GROUP BY
    zcta
),

-- Early aggregation of category & SKU demand velocity per ZCTA
zcta_category_agg AS (
  SELECT
    zcta,
    CAST(item.item_category AS STRING) AS item_category,
    COUNTIF(event_name = 'view_item') AS cat_views,
    COUNTIF(event_name = 'add_to_cart') AS cat_carts,
    COUNTIF(event_name = 'purchase') AS cat_purchases
  FROM
    user_resolved_zcta,
    UNNEST(items) AS item
  WHERE
    zcta IS NOT NULL
    AND item.item_category IS NOT NULL
  GROUP BY
    zcta,
    CAST(item.item_category AS STRING)
),

top_zcta_category AS (
  SELECT
    zcta,
    ARRAY_AGG(item_category ORDER BY (cat_views + cat_carts * 2 + cat_purchases * 4) DESC LIMIT 1)[OFFSET(0)] AS dominant_category
  FROM
    zcta_category_agg
  GROUP BY
    zcta
)

SELECT
  f.zcta,
  f.primary_resolution_tier,
  f.active_users,
  f.total_sessions,
  f.item_views,
  f.cart_additions,
  f.checkouts,
  f.purchases,
  f.total_revenue_usd,
  ROUND(SAFE_DIVIDE(f.purchases, GREATEST(1, f.total_sessions)), 4) AS conversion_rate,
  ROUND(SAFE_DIVIDE(f.cart_additions, GREATEST(1, f.item_views)), 4) AS view_to_cart_rate,
  ROUND(SAFE_DIVIDE(f.total_revenue_usd, GREATEST(1, f.active_users)), 2) AS revenue_per_user,
  ROUND(SAFE_DIVIDE(f.paid_ad_events, GREATEST(1, f.total_events)), 4) AS paid_saturation_ratio,
  COALESCE(tc.dominant_category, 'Electronics') AS dominant_category,
  -- Classify top-decile high-volume ZCTAs as Seed Champions for Use Case A
  IF(
    f.active_users >= 45 AND SAFE_DIVIDE(f.purchases, GREATEST(1, f.total_sessions)) >= 0.085,
    TRUE,
    FALSE
  ) AS is_seed_champion
FROM
  zcta_funnel_agg f
LEFT JOIN
  top_zcta_category tc ON f.zcta = tc.zcta;


-- ----------------------------------------------------------------------------
-- STEP 2: Materialize PDI 330-Dim Subspaces & Interpretable Environmental Indices
-- Slices the 330-element `features` ARRAY<FLOAT64> into its 3 canonical domains:
--   - Indices 0..127   (128 dims): Aggregated Search Trends
--   - Indices 128..255 (128 dims): Maps & Busyness (POIs, foot traffic, built env)
--   - Indices 256..329 (74 dims) : Weather & Air Quality
-- ----------------------------------------------------------------------------
CREATE OR REPLACE TABLE `ga4demo-503822.analytics_312456789.pdi_zcta_subspaces` AS
SELECT
  geo_id AS zcta,
  geo_name,
  administrative_area_level_1_id,
  administrative_area_level_1_name AS state_name,
  administrative_area_level_2_id,
  administrative_area_level_2_name AS county_name,
  features AS full_330d_embedding,

  -- Subspace 1: Search Trends (Indices 0 to 127)
  ARRAY(
    SELECT val FROM UNNEST(features) AS val WITH OFFSET idx
    WHERE idx BETWEEN 0 AND 127
    ORDER BY idx
  ) AS vec_search_0_127,

  -- Subspace 2: Maps & Busyness (Indices 128 to 255)
  ARRAY(
    SELECT val FROM UNNEST(features) AS val WITH OFFSET idx
    WHERE idx BETWEEN 128 AND 255
    ORDER BY idx
  ) AS vec_maps_128_255,

  -- Subspace 3: Weather & Air Quality (Indices 256 to 329)
  ARRAY(
    SELECT val FROM UNNEST(features) AS val WITH OFFSET idx
    WHERE idx BETWEEN 256 AND 329
    ORDER BY idx
  ) AS vec_weather_256_329,

  -- Interpretable scalar indices derived from PDI subspace activations (0.0 to 1.0)
  ROUND(
    (SELECT AVG(ABS(val)) FROM UNNEST(features) AS val WITH OFFSET idx WHERE idx BETWEEN 0 AND 127),
    4
  ) AS pdi_search_intent_index,
  ROUND(
    (SELECT AVG(ABS(val)) FROM UNNEST(features) AS val WITH OFFSET idx WHERE idx BETWEEN 128 AND 255),
    4
  ) AS pdi_retail_busyness_index,
  ROUND(
    (SELECT AVG(ABS(val)) FROM UNNEST(features) AS val WITH OFFSET idx WHERE idx BETWEEN 256 AND 329),
    4
  ) AS pdi_weather_friction_index
FROM
  `ga4demo-503822.analytics_312456789.pdi_zcta_embeddings`
WHERE
  ARRAY_LENGTH(features) = 330;


-- ----------------------------------------------------------------------------
-- STEP 3 (USE CASE A): Lookalike / Geo-Expansion Engine
-- Computes the Seed Champion Centroid across each PDI subspace, evaluates
-- Subspace-Weighted Cosine Similarity via `ML.DISTANCE(..., 'COSINE')`, and
-- ranks under-penetrated candidate ZCTAs by White-Space Opportunity Score.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE TABLE `ga4demo-503822.analytics_312456789.geo_expansion_lookalikes` AS
WITH seed_zctas AS (
  SELECT
    p.zcta,
    p.vec_search_0_127,
    p.vec_maps_128_255,
    p.vec_weather_256_329
  FROM
    `ga4demo-503822.analytics_312456789.pdi_zcta_subspaces` p
  INNER JOIN
    `ga4demo-503822.analytics_312456789.ga4_zcta_performance` g
    ON p.zcta = g.zcta
  WHERE
    g.is_seed_champion = TRUE
),

-- Compute element-wise mean centroid vectors for the 3 PDI subspaces across Seed Champions
seed_search_centroid AS (
  SELECT ARRAY_AGG(avg_val ORDER BY idx) AS c_search
  FROM (
    SELECT idx, AVG(val) AS avg_val
    FROM seed_zctas, UNNEST(vec_search_0_127) AS val WITH OFFSET idx
    GROUP BY idx
  )
),
seed_maps_centroid AS (
  SELECT ARRAY_AGG(avg_val ORDER BY idx) AS c_maps
  FROM (
    SELECT idx, AVG(val) AS avg_val
    FROM seed_zctas, UNNEST(vec_maps_128_255) AS val WITH OFFSET idx
    GROUP BY idx
  )
),
seed_weather_centroid AS (
  SELECT ARRAY_AGG(avg_val ORDER BY idx) AS c_weather
  FROM (
    SELECT idx, AVG(val) AS avg_val
    FROM seed_zctas, UNNEST(vec_weather_256_329) AS val WITH OFFSET idx
    GROUP BY idx
  )
),

-- Evaluate Subspace Cosine Similarities once per ZCTA (Common Subexpression Reuse)
subspace_similarities AS (
  SELECT
    p.zcta,
    p.geo_name,
    p.state_name,
    p.county_name,
    p.pdi_search_intent_index,
    p.pdi_retail_busyness_index,
    p.pdi_weather_friction_index,
    COALESCE(g.is_seed_champion, FALSE) AS is_seed_champion,
    COALESCE(g.active_users, 0) AS current_ga4_users,
    COALESCE(g.conversion_rate, 0.0) AS current_ga4_cvr,
    COALESCE(g.revenue_per_user, 0.0) AS current_revenue_per_user,
    COALESCE(g.paid_saturation_ratio, 0.05) AS paid_saturation_ratio,
    COALESCE(g.dominant_category, 'Electronics') AS recommended_category,

    -- Cosine similarity = 1.0 - ML.DISTANCE(v, centroid, 'COSINE')
    ROUND(1.0 - ML.DISTANCE(p.vec_search_0_127, sc.c_search, 'COSINE'), 4) AS sim_search_0_127,
    ROUND(1.0 - ML.DISTANCE(p.vec_maps_128_255, mc.c_maps, 'COSINE'), 4) AS sim_maps_128_255,
    ROUND(1.0 - ML.DISTANCE(p.vec_weather_256_329, wc.c_weather, 'COSINE'), 4) AS sim_weather_256_329
  FROM
    `ga4demo-503822.analytics_312456789.pdi_zcta_subspaces` p
  CROSS JOIN seed_search_centroid sc
  CROSS JOIN seed_maps_centroid mc
  CROSS JOIN seed_weather_centroid wc
  LEFT JOIN
    `ga4demo-503822.analytics_312456789.ga4_zcta_performance` g
    ON p.zcta = g.zcta
),

scored_lookalikes AS (
  SELECT
    *,
    -- Default Subspace Weights: 45% Search Intent, 40% Maps/Busyness, 15% Weather/Climate
    ROUND(
      0.45 * sim_search_0_127 + 0.40 * sim_maps_128_255 + 0.15 * sim_weather_256_329,
      4
    ) AS composite_pdi_similarity,

    -- White-Space Opportunity Score penalizes already-saturated paid markets
    ROUND(
      (0.45 * sim_search_0_127 + 0.40 * sim_maps_128_255 + 0.15 * sim_weather_256_329)
      * POW(GREATEST(0.10, 1.0 - paid_saturation_ratio), 0.65),
      4
    ) AS whitespace_opportunity_score
  FROM
    subspace_similarities
)

SELECT
  zcta,
  geo_name,
  state_name,
  county_name,
  is_seed_champion,
  sim_search_0_127,
  sim_maps_128_255,
  sim_weather_256_329,
  composite_pdi_similarity,
  whitespace_opportunity_score,
  current_ga4_users,
  current_ga4_cvr,
  current_revenue_per_user,
  paid_saturation_ratio,
  recommended_category,
  pdi_search_intent_index,
  pdi_retail_busyness_index,
  pdi_weather_friction_index,
  -- Predict incremental ROAS based on similarity to Seed Champions & white-space headroom
  ROUND(1.8 + 3.4 * whitespace_opportunity_score, 2) AS predicted_expansion_roas,
  CASE
    WHEN is_seed_champion THEN 'Seed Champion (Reference Market)'
    WHEN composite_pdi_similarity >= 0.86 AND paid_saturation_ratio <= 0.25 THEN 'Tier 1 Lookalike Expansion (High Priority)'
    WHEN composite_pdi_similarity >= 0.78 THEN 'Tier 2 Lookalike Expansion (Moderate Priority)'
    ELSE 'Hold / Low Similarity'
  END AS expansion_tier
FROM
  scored_lookalikes
ORDER BY
  is_seed_champion DESC,
  whitespace_opportunity_score DESC;


-- ----------------------------------------------------------------------------
-- STEP 4 (USE CASE B): Stock-Aware Demand Routing (PDI + GA4 + Inventory)
-- Joins ZCTA lookalike & demand metrics with `zcta_store_sku_inventory`,
-- calculates Effective Days of Supply (`effective_days_of_supply`), and assigns
-- each (ZCTA, SKU) pair to:
--   1. `IN_STORE_BOPIS_LIA` ("In-Store Near You" Local Inventory Ads)
--   2. `DTC_WAREHOUSE_SHIP` (Route to DTC Ship-to-Home + Personalized Offer)
--   3. `SUPPRESS_HOLD_SPEND` (Pause SKU Spend — Local & DTC Constrained)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE TABLE `ga4demo-503822.analytics_312456789.stock_aware_routing_decisions` AS
WITH inventory_with_signals AS (
  SELECT
    inv.zcta,
    l.geo_name,
    l.state_name,
    l.expansion_tier,
    l.composite_pdi_similarity,
    l.whitespace_opportunity_score,
    l.pdi_search_intent_index,
    l.pdi_retail_busyness_index,
    l.pdi_weather_friction_index,
    inv.item_id,
    inv.item_name,
    inv.item_category,
    inv.unit_price_usd,
    inv.store_id,
    inv.store_name,
    inv.distance_to_store_miles,
    inv.store_on_hand_units,
    inv.base_daily_store_sales,
    inv.dtc_warehouse_id,
    inv.dtc_available_units,
    inv.ga4_local_demand_velocity,

    -- Predicted Daily Store Burn combines base sales + GA4 online velocity + PDI foot-traffic busyness
    ROUND(
      GREATEST(
        0.5,
        inv.base_daily_store_sales
        * (1.0 + 0.50 * inv.ga4_local_demand_velocity)
        * (1.0 + 0.60 * l.pdi_retail_busyness_index)
        * (1.0 - 0.25 * l.pdi_weather_friction_index)
      ),
      2
    ) AS predicted_daily_burn_units
  FROM
    `ga4demo-503822.analytics_312456789.zcta_store_sku_inventory` inv
  INNER JOIN
    `ga4demo-503822.analytics_312456789.geo_expansion_lookalikes` l
    ON inv.zcta = l.zcta
),

edos_evaluated AS (
  SELECT
    *,
    ROUND(SAFE_DIVIDE(store_on_hand_units, predicted_daily_burn_units), 1) AS effective_days_of_supply,
    -- In-store visit propensity combines PDI Maps/Busyness, store proximity, and fair weather
    ROUND(
      LEAST(
        0.98,
        GREATEST(
          0.05,
          0.65 * pdi_retail_busyness_index
          + 0.35 * (1.0 - LEAST(1.0, distance_to_store_miles / 25.0))
          - 0.30 * pdi_weather_friction_index
        )
      ),
      4
    ) AS in_store_visit_propensity
  FROM
    inventory_with_signals
)

SELECT
  zcta,
  geo_name,
  state_name,
  expansion_tier,
  composite_pdi_similarity,
  whitespace_opportunity_score,
  item_id,
  item_name,
  item_category,
  unit_price_usd,
  store_id,
  store_name,
  distance_to_store_miles,
  store_on_hand_units,
  predicted_daily_burn_units,
  effective_days_of_supply,
  dtc_warehouse_id,
  dtc_available_units,
  ga4_local_demand_velocity,
  pdi_retail_busyness_index,
  pdi_weather_friction_index,
  in_store_visit_propensity,

  -- 3-Way Stock-Aware Demand Routing Decision
  CASE
    WHEN store_on_hand_units >= 8
         AND effective_days_of_supply >= 3.5
         AND distance_to_store_miles <= 15.0
         AND in_store_visit_propensity >= 0.42
      THEN 'IN_STORE_BOPIS_LIA'
    WHEN dtc_available_units >= 25
      THEN 'DTC_WAREHOUSE_SHIP'
    ELSE 'SUPPRESS_HOLD_SPEND'
  END AS routing_channel_decision,

  -- Dynamic Ad Campaign Action & Bid Modifier
  CASE
    WHEN store_on_hand_units >= 8
         AND effective_days_of_supply >= 3.5
         AND distance_to_store_miles <= 15.0
         AND in_store_visit_propensity >= 0.42
      THEN CONCAT('Trigger Local Inventory Ads (BOPIS at ', store_name, ') | +35% Geo Bid Boost')
    WHEN dtc_available_units >= 25
      THEN CONCAT('Route to DTC Shopping/PMax (', dtc_warehouse_id, ') | Suppress Store Extensions')
    ELSE 'Pause SKU Paid Media in ZCTA (Protect ROAS from Stockout)'
  END AS ad_campaign_action,

  -- Dynamic Storefront Creative Headline
  CASE
    WHEN store_on_hand_units >= 8
         AND effective_days_of_supply >= 3.5
         AND distance_to_store_miles <= 15.0
         AND in_store_visit_propensity >= 0.42
      THEN CONCAT('In Stock Near You (', zcta, '): Pick Up ', item_name, ' Today at ', store_name, ' (', CAST(store_on_hand_units AS STRING), ' Available)!')
    WHEN dtc_available_units >= 25
      THEN CONCAT('Fast Direct Delivery to ', zcta, ': Get ', item_name, ' Shipped Free from Our DTC Fulfillment Center!')
    ELSE CONCAT(item_name, ' Is High-Demand in ', zcta, ' — Get Restock Alert & Explore Similar Favorites')
  END AS dynamic_creative_headline
FROM
  edos_evaluated;


-- ----------------------------------------------------------------------------
-- STEP 5: Closed-Loop 1:1 User + Geo + Stock Activation View
-- Joins individual GA4 users (`user_micro_segments`) with their resolved ZCTA's
-- Use Case A lookalike score and Use Case B stock-aware routing decision.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `ga4demo-503822.analytics_312456789.v_user_geo_stock_activation` AS
SELECT
  u.user_pseudo_id,
  u.user_id,
  u.propensity_score,
  u.personalized_discount_pct,
  u.coupon_code,
  u.top_category_affinity,
  r.zcta,
  r.geo_name,
  r.expansion_tier,
  r.composite_pdi_similarity,
  r.item_id AS routed_sku_id,
  r.item_name AS routed_sku_name,
  r.store_name AS nearest_store_name,
  r.store_on_hand_units,
  r.effective_days_of_supply,
  r.dtc_available_units,
  r.routing_channel_decision,
  r.ad_campaign_action,
  CASE
    WHEN r.routing_channel_decision = 'IN_STORE_BOPIS_LIA'
      THEN CONCAT(r.dynamic_creative_headline, ' | Reserve with Code ', u.coupon_code, ' (', CAST(u.personalized_discount_pct AS STRING), '% Off)')
    WHEN r.routing_channel_decision = 'DTC_WAREHOUSE_SHIP'
      THEN CONCAT(r.dynamic_creative_headline, ' | Extra ', CAST(u.personalized_discount_pct AS STRING), '% Off Online with ', u.coupon_code)
    ELSE r.dynamic_creative_headline
  END AS omnichannel_1to1_banner
FROM
  `ga4demo-503822.analytics_312456789.user_micro_segments` u
INNER JOIN
  `ga4demo-503822.analytics_312456789.user_zcta_mapping` uz
  ON u.user_pseudo_id = uz.user_pseudo_id
INNER JOIN
  `ga4demo-503822.analytics_312456789.stock_aware_routing_decisions` r
  ON uz.zcta = r.zcta
  AND u.top_category_affinity = r.item_category;
