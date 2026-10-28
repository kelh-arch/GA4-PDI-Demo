/**
 * PDI × GA4 × Stock Inventory Command Center Frontend Engine
 * Supports instant client-side subspace cosine similarity & eDOS routing calculations
 * as well as backend API synchronization.
 */

let APP_DATA = null;
let PAYLOADS_CACHE = {};
let SQL_TEXT = "";
let ACTIVE_SEED_FILTER = "ALL";
let QUALIFIED_ZCTAS = new Set();
let SELECTED_ROUTING_ZCTA = "94043";

function cosineSim(vecA, vecB) {
    let dot = 0.0, normA = 0.0, normB = 0.0;
    for (let i = 0; i < vecA.length; i++) {
        dot += vecA[i] * vecB[i];
        normA += vecA[i] * vecA[i];
        normB += vecB[i] * vecB[i];
    }
    if (normA === 0 || normB === 0) return 0;
    return Math.max(0, Math.min(1, dot / (Math.sqrt(normA) * Math.sqrt(normB))));
}

function switchTab(tabId, btnEl) {
    document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
    const target = document.getElementById(tabId);
    if (target) target.classList.add('active');
    if (btnEl) btnEl.classList.add('active');
}

async function initApp() {
    try {
        const res = await fetch('api/pdi_geo_stock_data.json');
        APP_DATA = await res.json();
    } catch (e) {
        const res = await fetch('/api/data');
        APP_DATA = await res.json();
    }

    if (APP_DATA.zctas && APP_DATA.zctas.length > 0) {
        SELECTED_ROUTING_ZCTA = APP_DATA.zctas[0].zcta;
    }

    populateSidebarStats();
    populateSeedsStrip();
    populateSkuSelector();
    recalcLookalikes();
    recalcRouting();
    renderUsersTable();
    loadPayloadsAndDocs();
}

function populateSidebarStats() {
    let t1 = 0, t2 = 0, t3 = 0;
    APP_DATA.zctas.forEach(z => {
        t1 += (z.tier1_share || 0) * (z.active_users || 1);
        t2 += (z.tier2_share || 0) * (z.active_users || 1);
        t3 += (z.tier3_share || 0) * (z.active_users || 1);
    });
    const total = (t1 + t2 + t3) || 1;
    document.getElementById('tier1-pct').textContent = Math.round((t1 / total) * 100) + '%';
    document.getElementById('tier2-pct').textContent = Math.round((t2 / total) * 100) + '%';
    document.getElementById('tier3-pct').textContent = Math.round((t3 / total) * 100) + '%';
}

function populateSeedsStrip() {
    const strip = document.getElementById('seed-champions-strip');
    const seeds = APP_DATA.zctas.filter(z => z.is_seed_champion);
    strip.innerHTML = seeds.map(s => `
        <div class="seed-card ${ACTIVE_SEED_FILTER === s.zcta ? 'active' : ''}" onclick="selectSeedFilter('${s.zcta}')">
            <div class="seed-zip">★ ${s.zcta}</div>
            <div class="seed-city">${s.geo_name}</div>
            <div class="seed-stat">ROAS: ${s.predicted_expansion_roas.toFixed(1)}x | $${(s.total_revenue_usd / 1000).toFixed(1)}k</div>
        </div>
    `).join('');
}

function selectSeedFilter(zcta) {
    ACTIVE_SEED_FILTER = zcta;
    populateSeedsStrip();
    recalcLookalikes();
}

function populateSkuSelector() {
    const sel = document.getElementById('select-sku');
    sel.innerHTML = APP_DATA.products.map(p =>
        `<option value="${p.id}">${p.id} — ${p.name} ($${p.price})</option>`
    ).join('');
}

function recalcLookalikes() {
    const wSearchRaw = parseFloat(document.getElementById('slider-w-search').value);
    const wMapsRaw = parseFloat(document.getElementById('slider-w-maps').value);
    const wWeatherRaw = parseFloat(document.getElementById('slider-w-weather').value);
    const minSim = parseFloat(document.getElementById('slider-min-sim').value);
    const maxSat = parseFloat(document.getElementById('slider-max-sat').value);

    const sumW = (wSearchRaw + wMapsRaw + wWeatherRaw) || 1.0;
    const wSearch = wSearchRaw / sumW;
    const wMaps = wMapsRaw / sumW;
    const wWeather = wWeatherRaw / sumW;

    document.getElementById('val-w-search').textContent = (wSearch * 100).toFixed(0) + '%';
    document.getElementById('val-w-maps').textContent = (wMaps * 100).toFixed(0) + '%';
    document.getElementById('val-w-weather').textContent = (wWeather * 100).toFixed(0) + '%';
    document.getElementById('val-min-sim').textContent = minSim.toFixed(2);
    document.getElementById('val-max-sat').textContent = Math.round(maxSat * 100) + '%';

    const seeds = APP_DATA.zctas.filter(z => z.is_seed_champion && (ACTIVE_SEED_FILTER === 'ALL' || z.zcta === ACTIVE_SEED_FILTER));
    const candidates = [];
    QUALIFIED_ZCTAS.clear();

    APP_DATA.zctas.filter(z => !z.is_seed_champion).forEach(cand => {
        let bestMatch = null;
        let bestComposite = -1;

        seeds.forEach(s => {
            const simS = cosineSim(cand.vec_search_0_127, s.vec_search_0_127);
            const simM = cosineSim(cand.vec_maps_128_255, s.vec_maps_128_255);
            const simW = cosineSim(cand.vec_weather_256_329, s.vec_weather_256_329);
            const comp = wSearch * simS + wMaps * simM + wWeather * simW;
            if (comp > bestComposite) {
                bestComposite = comp;
                bestMatch = {
                    seed_zcta: s.zcta,
                    seed_name: s.geo_name,
                    simS, simM, simW,
                    composite: comp
                };
            }
        });

        const paidSat = cand.paid_saturation_ratio;
        const whiteSpace = bestComposite * Math.pow(Math.max(0.10, 1.0 - paidSat), 0.65);
        const qualified = bestComposite >= minSim && paidSat <= maxSat;
        if (qualified) QUALIFIED_ZCTAS.add(cand.zcta);

        candidates.push({
            ...cand,
            bestMatch,
            whiteSpace,
            qualified
        });
    });

    candidates.sort((a, b) => b.whiteSpace - a.whiteSpace);
    document.getElementById('kpi-qualified').textContent = QUALIFIED_ZCTAS.size + ' / ' + candidates.length;

    const tbody = document.getElementById('lookalike-table-body');
    tbody.innerHTML = candidates.map(c => {
        const m = c.bestMatch;
        const sPct = Math.max(0, Math.min(100, Math.round(m.simS * 100)));
        const mPct = Math.max(0, Math.min(100, Math.round(m.simM * 100)));
        const wPct = Math.max(0, Math.min(100, Math.round(m.simW * 100)));

        return `
            <tr class="clickable-row" onclick="inspectZctaInRouter('${c.zcta}')">
                <td>
                    <div style="font-weight:700; font-family:var(--font-mono); color:#f8fafc;">${c.zcta}</div>
                    <div style="font-size:0.74rem; color:var(--text-secondary);">${c.geo_name}</div>
                </td>
                <td>
                    <span class="badge badge-seed">★ ${m.seed_zcta}</span>
                    <div style="font-size:0.71rem; color:var(--text-muted); margin-top:2px;">${m.seed_name}</div>
                </td>
                <td>
                    <div class="subspace-bars">
                        <div class="subbar-row">
                            <span style="width:42px; color:#60a5fa;">Search</span>
                            <div class="subbar-track"><div class="subbar-fill" style="width:${sPct}%; background:#3b82f6;"></div></div>
                            <span>${m.simS.toFixed(2)}</span>
                        </div>
                        <div class="subbar-row">
                            <span style="width:42px; color:#34d399;">Maps</span>
                            <div class="subbar-track"><div class="subbar-fill" style="width:${mPct}%; background:#10b981;"></div></div>
                            <span>${m.simM.toFixed(2)}</span>
                        </div>
                        <div class="subbar-row">
                            <span style="width:42px; color:#fbbf24;">Weath</span>
                            <div class="subbar-track"><div class="subbar-fill" style="width:${wPct}%; background:#f59e0b;"></div></div>
                            <span>${m.simW.toFixed(2)}</span>
                        </div>
                    </div>
                </td>
                <td style="font-family:var(--font-mono); font-weight:700; color:#e2e8f0;">
                    ${m.composite.toFixed(3)}
                </td>
                <td style="font-family:var(--font-mono);">
                    ${Math.round(c.paid_saturation_ratio * 100)}%
                    <div style="font-size:0.68rem; color:var(--text-muted);">${c.active_users} GA4 users</div>
                </td>
                <td style="font-family:var(--font-mono); font-weight:700; color:#38bdf8;">
                    ${c.whiteSpace.toFixed(3)}
                </td>
                <td>
                    ${c.qualified
                        ? '<span class="badge badge-bopis">QUALIFIED EXPANSION</span>'
                        : '<span class="badge" style="background:rgba(148,163,184,0.12); color:#94a3b8;">BELOW THRESHOLD</span>'}
                </td>
            </tr>
        `;
    }).join('');
}

function pushExpansionToRouter() {
    document.getElementById('select-cohort-filter').value = 'QUALIFIED_PLUS_SEEDS';
    const navButtons = document.querySelectorAll('.nav-btn');
    switchTab('tab-routing', navButtons[1]);
    recalcRouting();
}

function inspectZctaInRouter(zcta) {
    SELECTED_ROUTING_ZCTA = zcta;
    const navButtons = document.querySelectorAll('.nav-btn');
    switchTab('tab-routing', navButtons[1]);
    recalcRouting();
}

function computeClientSideRouting(z, skuEntry, minEdos, busynessW, weatherW, maxDist) {
    const localStock = skuEntry.store_on_hand_units;
    const safety = 6;
    const dtcStock = skuEntry.dtc_available_units;
    const baseSales = skuEntry.base_daily_store_sales;
    const ga4Vel = skuEntry.ga4_local_demand_velocity;
    const busyness = z.pdi_retail_busyness_index;
    const weatherFriction = z.pdi_weather_friction_index;
    const dist = skuEntry.distance_to_store_miles;

    const burnRate = Math.max(
        0.5,
        baseSales * (1.0 + 0.50 * ga4Vel) * (1.0 + busynessW * busyness) * (1.0 - 0.25 * weatherFriction)
    );
    const edos = localStock / burnRate;

    const distPenalty = Math.min(1.0, dist / Math.max(1.0, maxDist));
    const visitPropensity = Math.max(
        0.05,
        Math.min(0.98, 0.65 * busyness + 0.35 * (1.0 - distPenalty) - weatherW * weatherFriction)
    );

    let channel = "SUPPRESS_HOLD_SPEND";
    let bidMod = -1.0;
    let adHeadline = `[PAUSED] ${skuEntry.item_name} Inventory Constrained in ${z.geo_name}`;
    let webBanner = `Out of Stock Locally & Online — Get Restock Alert & Explore Similar Favorites`;

    if (localStock >= 8 && edos >= minEdos && dist <= maxDist && visitPropensity >= 0.40) {
        channel = "IN_STORE_BOPIS_LIA";
        bidMod = +(0.15 + 0.30 * visitPropensity).toFixed(2);
        adHeadline = `In Stock Near You (${z.zcta}): Pick Up ${skuEntry.item_name} Today at ${z.store_name} (${localStock} Available)!`;
        webBanner = `🔥 ${localStock} Ready for 1-Hour Store Pickup at ${z.store_name} (${dist} mi)`;
    } else if (dtcStock >= 25) {
        channel = "DTC_WAREHOUSE_SHIP";
        bidMod = +(0.10 + 0.15 * (1.0 - visitPropensity)).toFixed(2);
        adHeadline = `Fast Direct Delivery to ${z.geo_name}: Get ${skuEntry.item_name} Shipped Free from ${z.dtc_warehouse_id}!`;
        webBanner = `📦 Store Stock Limited Near ${z.zcta} (${ skuEntry.scenario_note }) — Ships Free Today`;
    }

    return {
        channel,
        safety,
        edos: +edos.toFixed(1),
        burnRate: +burnRate.toFixed(1),
        visitPropensity: +visitPropensity.toFixed(2),
        bidMod,
        adHeadline,
        webBanner
    };
}

function recalcRouting() {
    const skuId = document.getElementById('select-sku').value || 'PROD-101';
    const cohortFilter = document.getElementById('select-cohort-filter').value;
    const minEdos = parseFloat(document.getElementById('slider-min-edos').value);
    const busynessW = parseFloat(document.getElementById('slider-busyness-w').value);
    const weatherW = parseFloat(document.getElementById('slider-weather-w').value);
    const maxDist = parseFloat(document.getElementById('slider-max-dist').value);

    document.getElementById('val-min-edos').textContent = minEdos.toFixed(1) + ' days';
    document.getElementById('val-busyness-w').textContent = busynessW.toFixed(2);
    document.getElementById('val-weather-w').textContent = weatherW.toFixed(2);
    document.getElementById('val-max-dist').textContent = maxDist.toFixed(1) + ' mi';

    let zctaList = APP_DATA.zctas;
    if (cohortFilter === 'SEEDS_ONLY') {
        zctaList = zctaList.filter(z => z.is_seed_champion);
    } else if (cohortFilter === 'QUALIFIED_PLUS_SEEDS') {
        zctaList = zctaList.filter(z => z.is_seed_champion || QUALIFIED_ZCTAS.has(z.zcta));
    }

    let bopisCount = 0, dtcCount = 0, holdCount = 0;
    const rowsHtml = [];

    zctaList.forEach(z => {
        const skuEntry = z.sku_inventory[skuId] || Object.values(z.sku_inventory)[0];
        const r = computeClientSideRouting(z, skuEntry, minEdos, busynessW, weatherW, maxDist);

        if (r.channel === 'IN_STORE_BOPIS_LIA') bopisCount++;
        else if (r.channel === 'DTC_WAREHOUSE_SHIP') dtcCount++;
        else holdCount++;

        if (z.zcta === SELECTED_ROUTING_ZCTA) {
            updateCreativePreview(z, skuEntry, r);
        }

        let badgeClass = 'badge-suppress';
        if (r.channel === 'IN_STORE_BOPIS_LIA') badgeClass = 'badge-bopis';
        else if (r.channel === 'DTC_WAREHOUSE_SHIP') badgeClass = 'badge-dtc';

        const bidStr = r.bidMod >= 0 ? `+${Math.round(r.bidMod * 100)}%` : `${Math.round(r.bidMod * 100)}%`;

        rowsHtml.push(`
            <tr class="clickable-row ${z.zcta === SELECTED_ROUTING_ZCTA ? 'selected-row' : ''}" onclick="selectRoutingRow('${z.zcta}')">
                <td>
                    <div style="display:flex; align-items:center; gap:6px;">
                        <span style="font-family:var(--font-mono); font-weight:700;">${z.zcta}</span>
                        ${z.is_seed_champion ? '<span class="badge badge-seed">SEED</span>' : '<span class="badge badge-lookalike">LOOKALIKE</span>'}
                    </div>
                    <div style="font-size:0.73rem; color:var(--text-secondary);">${z.geo_name} • ${z.store_name} (${z.distance_to_store_miles} mi)</div>
                </td>
                <td style="font-family:var(--font-mono);">
                    <strong style="color:${skuEntry.store_on_hand_units >= 8 ? '#34d399' : '#fb7185'}">${skuEntry.store_on_hand_units} units</strong>
                    <div style="font-size:0.68rem; color:var(--text-muted);">Burn: ${r.burnRate}/d</div>
                </td>
                <td style="font-family:var(--font-mono);">
                    ${skuEntry.dtc_available_units} units
                    <div style="font-size:0.68rem; color:var(--text-muted);">${z.dtc_warehouse_id}</div>
                </td>
                <td style="font-family:var(--font-mono); font-size:0.74rem;">
                    Busy: ${(z.pdi_retail_busyness_index * 100).toFixed(0)}%<br>
                    Weath Friction: ${(z.pdi_weather_friction_index * 100).toFixed(0)}%
                </td>
                <td style="font-family:var(--font-mono); font-weight:700; color:${r.edos >= minEdos ? '#34d399' : '#fbbf24'};">
                    ${r.edos.toFixed(1)} d
                </td>
                <td style="font-family:var(--font-mono);">
                    ${Math.round(r.visitPropensity * 100)}%
                </td>
                <td>
                    <span class="badge ${badgeClass}">${r.channel}</span>
                    <div style="font-size:0.7rem; font-family:var(--font-mono); color:var(--text-secondary); margin-top:3px;">
                        Bid Mod: ${bidStr}
                    </div>
                </td>
            </tr>
        `);
    });

    document.getElementById('kpi-bopis').textContent = bopisCount + ' ZCTAs';
    document.getElementById('kpi-dtc-hold').textContent = `${dtcCount} DTC / ${holdCount} Hold`;
    document.getElementById('routing-table-body').innerHTML = rowsHtml.join('');
}

function selectRoutingRow(zcta) {
    SELECTED_ROUTING_ZCTA = zcta;
    recalcRouting();
}

function updateCreativePreview(z, skuEntry, r) {
    document.getElementById('selected-zcta-preview-label').textContent =
        `ZCTA ${z.zcta} (${z.geo_name}) × ${skuEntry.item_name} ($${skuEntry.unit_price_usd})`;

    const badge = document.getElementById('preview-channel-badge');
    badge.textContent = r.channel;
    badge.className = 'badge ' + (
        r.channel === 'IN_STORE_BOPIS_LIA' ? 'badge-bopis' :
        r.channel === 'DTC_WAREHOUSE_SHIP' ? 'badge-dtc' : 'badge-suppress'
    );

    document.getElementById('preview-ad-headline').textContent = r.adHeadline;
    document.getElementById('preview-ad-meta').textContent =
        `Target Geo: US-${z.zcta} | Bid Adjustment: ${r.bidMod >= 0 ? '+' : ''}${Math.round(r.bidMod * 100)}% | Store: ${z.store_name} (${z.distance_to_store_miles} mi) | eDOS: ${r.edos} days`;

    document.getElementById('preview-web-banner').textContent = r.webBanner;
    document.getElementById('preview-web-meta').textContent =
        `Local Stock: ${skuEntry.store_on_hand_units} units | Central DTC Stock (${z.dtc_warehouse_id}): ${skuEntry.dtc_available_units} units | PDI Visit Propensity: ${Math.round(r.visitPropensity * 100)}%`;
}

function renderUsersTable() {
    const tbody = document.getElementById('users-table-body');
    const zctaMap = {};
    APP_DATA.zctas.forEach(z => { zctaMap[z.zcta] = z; });

    const users = (APP_DATA.sample_users || []).slice(0, 80);
    tbody.innerHTML = users.map(u => {
        const z = zctaMap[u.zcta] || APP_DATA.zctas[0];
        const skuEntry = z.sku_inventory['PROD-101'] || Object.values(z.sku_inventory)[0];
        const r = computeClientSideRouting(z, skuEntry, 3.5, 0.50, 0.35, 15.0);

        let badgeClass = 'badge-suppress';
        if (r.channel === 'IN_STORE_BOPIS_LIA') badgeClass = 'badge-bopis';
        else if (r.channel === 'DTC_WAREHOUSE_SHIP') badgeClass = 'badge-dtc';

        return `
            <tr>
                <td>
                    <div style="font-family:var(--font-mono); font-weight:700;">${u.user_pseudo_id}</div>
                    <div style="font-size:0.72rem; color:var(--text-secondary);">${u.cohort_name} • LTV $${u.predicted_ltv_365d}</div>
                </td>
                <td>
                    <span style="font-family:var(--font-mono); font-weight:700; color:#fbbf24;">${u.zcta}</span>
                    <span style="font-size:0.72rem; color:var(--text-secondary);"> (${u.geo_name})</span>
                    <div style="font-size:0.68rem; color:var(--accent-cyan); font-family:var(--font-mono);">${u.geo_resolution_tier}</div>
                </td>
                <td>
                    <div style="font-weight:600;">${u.top_category_affinity} (${skuEntry.item_name})</div>
                    <div style="font-size:0.7rem; font-family:var(--font-mono); color:var(--text-muted);">
                        Local: ${skuEntry.store_on_hand_units}u | eDOS: ${r.edos}d
                    </div>
                </td>
                <td>
                    <span class="badge ${badgeClass}">${r.channel}</span>
                    <div style="font-size:0.7rem; color:#e2e8f0; margin-top:3px;">
                        Offer: <code>${u.coupon_code}</code> (${u.personalized_discount_pct}% off)
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

async function loadPayloadsAndDocs() {
    try {
        let res = await fetch('api/payloads.json');
        if (!res.ok) res = await fetch('/api/payloads');
        if (res.ok) {
            PAYLOADS_CACHE = await res.json();
            showPayload('google_ads_geo_lia_payload.json');
        }
    } catch (e) {
        document.getElementById('payload-json-viewer').textContent =
            JSON.stringify((APP_DATA.sample_users || []).slice(0, 15), null, 2);
    }

    try {
        let res = await fetch('api/docs.json');
        if (!res.ok) res = await fetch('/api/docs');
        if (res.ok) {
            const docs = await res.json();
            SQL_TEXT = docs.sql || "";
            document.getElementById('sql-code-viewer').textContent = SQL_TEXT;
        }
    } catch (e) {
        document.getElementById('sql-code-viewer').textContent =
            "-- Run `python3 app.py` to view the full pdi_geo_inventory_queries.sql in the browser.";
    }
}

function showPayload(filename) {
    const viewer = document.getElementById('payload-json-viewer');
    if (PAYLOADS_CACHE[filename]) {
        viewer.textContent = JSON.stringify(PAYLOADS_CACHE[filename], null, 2);
    } else if (APP_DATA) {
        viewer.textContent = JSON.stringify((APP_DATA.sample_users || []).slice(0, 15), null, 2);
    }
}

function copySqlCode() {
    if (!SQL_TEXT) return;
    navigator.clipboard.writeText(SQL_TEXT);
    alert("Copied BigQuery SQL pipeline to clipboard!");
}

window.addEventListener('DOMContentLoaded', initApp);
