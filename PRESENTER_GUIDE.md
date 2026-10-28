# Presenter Guide: PDI × GA4 × Stock Inventory Command Center

**Live Dashboard:** [https://ga4demo-pdi.web.app](https://ga4demo-pdi.web.app)  
**Local Server:** `python3 app.py --port 8081` → `http://localhost:8081`

---

## 1. Opening Hook (30 Seconds) — The Strategic Gap

> *"Most retail and omni-channel marketers have a massive blind spot between three datasets that live in silos:*
> 1. **GA4** tells us *who* is browsing and buying online, and *which* ZIP codes convert today—but it tells us nothing about physical neighborhoods where we don't yet have traffic, or whether a physical store actually has inventory on the shelf.
> 2. **Google Maps Population Dynamics Insights (PDI)** gives us a 330-dimensional behavioral fingerprint for every US 5-digit ZIP code (`ZCTA`), decomposed into three distinct real-world signals:
>    - **Dimensions `0–127`:** Google Search Trends & category interest
>    - **Dimensions `128–255`:** Google Maps place density & live foot-traffic busyness
>    - **Dimensions `256–329`:** Local Weather & Air Quality (precipitation, temperature extremes, visit friction)
> 3. **Store & Warehouse ERP Stock** tells us where units physically sit right now.
>
> *This Command Center joins all three in BigQuery to solve two high-ROI problems: **Use Case A (Geo-Expansion Lookalikes)** and **Use Case B (Stock-Aware Demand Routing)**."*

Point briefly to the **4 KPI Hero Cards** at the top of the dashboard:
- **`20` Active ZCTAs** (`330-dim` PDI vectors across 5 Seed Benchmarks + 15 Candidate Expansion ZIPs)
- **`8` Ranked White-Space Expansion ZCTAs** discovered via PDI cosine similarity
- **`$184,592` Annualized Ad Waste Prevented** by automatically rerouting or pausing local store campaigns before stock-outs happen
- **`13,465` Real GA4 User Profiles** mapped to ZCTAs via our 3-tier waterfall (`89.0%` match coverage)

---

## 2. Act I: Use Case A — Lookalike & Geo-Expansion (Tab A)

**Narrative Goal:** Show how PDI finds "hidden twin" ZIP codes where your ideal customers live and shop, even if GA4 currently shows zero or low web traffic there.

### Step-by-Step Live Walkthrough:
1. **Show the Seed Benchmark ZIPs (`Top Performers`):**
   - Point out that we take our top 10% converting GA4 ZIP codes (like **SoHo NY `10013`**, **Beverly Hills `90210`**, **Miami Beach `33139`**, **Lincoln Park Chicago `60614`**, and **Austin Downtown `78701`**) and build a revenue-weighted **330-d PDI Centroid Vector**.
2. **Interactive Demo — Adjust the PDI Subspace Sliders:**
   - Show the three sliders on the left:
     - **Search (`0–127`)**: Online search intent
     - **Maps (`128–255`)**: Physical retail density & foot traffic busyness
     - **Weather (`256–329`)**: Climate & seasonal similarity
   - **Action:** Click the **"Foot-Traffic Heavy"** preset (or drag the Maps slider up to `70%`) and click **Recompute Similarity**.
   - **Talking Point:** *"Notice how we don't treat the 330 dimensions as a black box. If we're launching a physical retail pop-up or Local Inventory Ad campaign, we weight the **Maps & Busyness (`128–255`)** subspace higher. If we're launching a seasonal rain/winter apparel campaign, we weight **Weather (`256–329`)** higher."*
3. **Inspect the Interactive US Map & Ranked Candidates Table:**
   - Click on top candidate **Williamsburg, Brooklyn (`11211`)** (`95.5%` PDI Similarity to SoHo `10013`) or **Scottsdale (`85251`)** (`92.7%` Similarity to Beverly Hills `90210`).
   - Point to the **Subspace Similarity Breakdown** panel on the right: show how `11211` matches `10013` across Search (`94.7%`), Maps (`96.6%`), and Weather (`94.6%`), yet has **low current GA4 penetration**—giving it the #1 **White-Space Opportunity Score** and a recommended **`+45%` Google Ads Geo Bid Modifier**.

---

## 3. Act II: Use Case B — Stock-Aware Demand Routing (Tab B)

**Narrative Goal:** Show how combining GA4 online velocity + PDI foot-traffic/weather + store inventory prevents wasted ad spend on out-of-stock stores and dynamically pivots campaigns between **In-Store Pickup (`BOPIS / LIA`)** and **DTC Warehouse Delivery**.

### Step-by-Step Live Walkthrough:
1. **Explain the Core Metric — `eDOS` (Effective Days of Supply):**
   - Point to the formula in the control bar:
     $$\text{eDOS} = \frac{\text{Available Local Store Units}}{\text{GA4 Online Velocity} + (\text{Physical Store Drain} \times \text{PDI Busyness} \times (1 - \text{PDI Weather Friction}))}$$
   - **Talking Point:** *"Standard inventory routing only looks at current shelf count. By injecting **GA4 online velocity** and **PDI Maps busyness + Weather friction**, we predict how many days of stock a store *actually* has left (`eDOS`)."*
2. **Walk Through the 3 Routing States in the Matrix Table:**
   - 🟢 **`IN_STORE_BOPIS_LIA` (Green — e.g., ZIP `10013` · Waterproof Shell):** `48` store units (`9.5` days supply) + sunny weather → Trigger **"In-Store Near You — Ready for 2-Hour Pickup"** Local Inventory Ads (`+35%` LIA bid boost).
   - 🔵 **`DTC_WAREHOUSE_SHIP` (Blue — two distinct triggers!):**
     - **Low Local Stock Trigger:** e.g., **ZIP `10001` · Running Shoe** has only `5` units left (`0.6` eDOS), while the Central DTC Warehouse has `890` units → Suppress store LIA ads immediately and route users to **DTC Free 2-Day Shipping** + a **1:1 GA4 Offer (`10% Off`)** so we don't lose the sale.
     - **Weather Friction Trigger:** Point out rainy/high-friction ZIPs where store stock is fine, but PDI Weather Friction is `>= 0.55` → Foot traffic is suppressed by rain, so we automatically pivot messaging from *"Walk In Today"* to *"Skip the Rain — Free Express Home Delivery"*.
   - 🔴 **`SUPPRESS_HOLD_SPEND` (Red — e.g., Thermal Fleece Hoodie):** Both the local store (`1–2` units) and the central DTC warehouse (`14` units) are depleted → Automatically **pause paid ad spend** and switch the PDP to a restock waitlist, saving thousands in wasted clicks.
3. **Interactive Demo — Run a Live Stock-Out / Weather Shock Simulation:**
   - In the **Live Stock-Out / Weather Shock Simulator** bar:
     - Select **`10013 — New York (SoHo), NY`**, **`SKU-JACKET-01 — Gore-Tex Waterproof Shell`**, set **Store Stock Override = `0`**, and click **Simulate Shock**.
   - **Watch the UI update live:** The row for `10013 × SKU-JACKET-01` flips from green (`IN_STORE_BOPIS_LIA`) to blue (`DTC_WAREHOUSE_SHIP`), `eDOS` drops to `0.0d`, and the **Annualized Ad Waste Prevented** counter ticks up!
   - Click **Reset** to restore the baseline state.
