# GA4 PDI Demo — Population Dynamics Insights (PDI) × GA4 × Stock Inventory Command Center

**Live Demo (Firebase Hosting):** [https://ga4demo-pdi.web.app](https://ga4demo-pdi.web.app)

Self-contained BigQuery SQL + Python + Interactive Web Demo showing how Google Maps Platform **Population Dynamics Insights (PDI)** (`330-dim` ZCTA embeddings) combines with **Google Analytics 4 (GA4)** behavioral data and **Store / DTC Inventory** for:

1. **Use Case A — Lookalike / Geo-Expansion**: Subspace-Weighted Cosine Similarity across PDI's 3 embedding subspaces (`0–127` Search Trends, `128–255` Maps & Busyness, `256–329` Weather & AQI) + White-Space Opportunity Scoring to discover under-penetrated high-potential 5-digit ZIP codes (ZCTAs).
2. **Use Case B — Stock-Aware Demand Routing**: Predictive Depletion (`Effective Days of Supply / eDOS`) combining GA4 online SKU velocity, PDI Maps retail foot-traffic busyness, PDI Weather visit friction, and real-time Local Store vs. Central DTC Warehouse stock to dynamically route each `(ZCTA, SKU)` pair to:
   - `IN_STORE_BOPIS_LIA` ("In-Store Near You" Local Inventory Ads + 2-Hour Pickup Banner)
   - `DTC_WAREHOUSE_SHIP` (DTC Ship-to-Home + 1:1 GA4 Offer when local stock is low or weather friction is high)
   - `SUPPRESS_HOLD_SPEND` (Automatic paid media pause when both local and central stock are constrained)

---

## Quickstart

### 1. Generate PDI 330-dim Embeddings, Inventory & Activation Payloads
```bash
python3 generate_pdi_stock_data.py
```
*(Optional: pass `--push_to_bq --project_id ga4demo-503822` to upload the mock PDI & stock tables directly into BigQuery, or `--pdi_table your-project.pdi_us.zcta_embeddings` to pull live PDI vectors).*

### 2. Launch the Interactive Command Center Locally
```bash
python3 app.py --port 8081
```
Open **`http://localhost:8081`** in your browser.

### 3. Deploy to Firebase Hosting (`ga4demo-pdi`)
```bash
npx -y firebase-tools@latest deploy --only hosting:ga4demo-pdi --project ga4demo-503822
```

---

## Repository Contents & Context
- [`PRESENTER_GUIDE.md`](PRESENTER_GUIDE.md) — Step-by-step live demo walkthrough, narrative talking points, and interactive simulation script.
- [`architecture_pdi_ga4_stock.md`](architecture_pdi_ga4_stock.md) — End-to-end architecture, 3-tier GA4-to-ZCTA waterfall, subspace similarity math, and `eDOS` routing matrix.
- [`pdi_geo_inventory_queries.sql`](pdi_geo_inventory_queries.sql) — 5-step production BigQuery SQL pipeline (`ML.DISTANCE` across PDI subspaces + `eDOS` stock routing + 1:1 user join).
- [`generate_pdi_stock_data.py`](generate_pdi_stock_data.py) — Hybrid PDI 330-d embedding & stock generator enriched with 13,465 real GA4 user profiles.
- [`app.py`](app.py) — Zero-dependency Python HTTP server with live `/api/simulate_lookalike` and `/api/simulate_routing` endpoints.
- [`static/`](static/) — Interactive Command Center frontend (`index.html`, `style.css`, `app.js`, and static `api/` JSON bundles for serverless hosting).
- [`activation_payloads/`](activation_payloads/) — Ready-to-sync JSON payloads for Google Ads Geo/LIA, DTC Web Personalization, and GA4 Measurement Protocol.
- [`mock_bq_tables/`](mock_bq_tables/) — Generated JSONL tables (`pdi_zcta_embeddings_330d.jsonl`, `store_dtc_inventory_live.jsonl`, `ga4_zcta_crosswalk.jsonl`) ready for BigQuery load.
- [`firebase.json`](firebase.json) & [`.firebaserc`](.firebaserc) — Firebase Hosting configuration targeting site `ga4demo-pdi` in project `ga4demo-503822`.
