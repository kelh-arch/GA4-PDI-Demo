#!/usr/bin/env python3
"""
PDI 330-Dim Embeddings + GA4 Geo-Resolution + Store/DTC Inventory Generator
===========================================================================
Builds synthetic/hybrid BigQuery tables and local JSON datasets for:
  - Use Case A: Lookalike / Geo-Expansion (330-dim PDI embeddings + GA4 seed KPIs)
  - Use Case B: Stock-Aware Demand Routing (PDI Maps/Weather + GA4 Velocity + Store/DTC Stock)

Usage:
  python3 generate_pdi_stock_data.py
  python3 generate_pdi_stock_data.py --push_to_bq --project_id ga4demo-503822 --dataset_id analytics_312456789
  python3 generate_pdi_stock_data.py --pdi_table my-project.pdi_dataset.zcta_embeddings
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import random
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
GA4_USERS_JSON = os.path.join(ROOT_DIR, "static", "api", "users.json")
OUTPUT_API_DIR = os.path.join(SCRIPT_DIR, "static", "api")
OUTPUT_PAYLOAD_DIR = os.path.join(SCRIPT_DIR, "activation_payloads")
OUTPUT_BQ_JSONL_DIR = os.path.join(SCRIPT_DIR, "mock_bq_tables")

# Product catalog matching `generate_ga4_mock_data.py`
PRODUCTS = [
    {"id": "PROD-101", "name": "Google Pixel 8 Pro", "brand": "Google", "category": "Electronics", "price": 999.00, "cogs_ratio": 0.42},
    {"id": "PROD-104", "name": "Nest Learning Thermostat", "brand": "Google", "category": "Smart Home", "price": 249.00, "cogs_ratio": 0.38},
    {"id": "PROD-107", "name": "Pixel Watch 2", "brand": "Google", "category": "Wearables", "price": 349.99, "cogs_ratio": 0.40},
    {"id": "PROD-102", "name": "Pixel Buds Pro", "brand": "Google", "category": "Audio", "price": 199.99, "cogs_ratio": 0.35},
    {"id": "PROD-103", "name": "Chromecast with Google TV", "brand": "Google", "category": "Electronics", "price": 49.99, "cogs_ratio": 0.45},
    {"id": "PROD-105", "name": "GCP Cloud Developer Hoodie", "brand": "Google Cloud", "category": "Apparel", "price": 65.00, "cogs_ratio": 0.30},
    {"id": "PROD-106", "name": "BigQuery Data Ninja Mug", "brand": "Google Cloud", "category": "Merchandise", "price": 18.50, "cogs_ratio": 0.25},
    {"id": "PROD-108", "name": "Tensor Processing Unit Plushie", "brand": "Google Cloud", "category": "Merchandise", "price": 25.00, "cogs_ratio": 0.28},
]

# 32 US ZCTAs (6 Seed Champion Markets from GA4 + 26 Candidate Lookalike & Omnichannel Markets)
ZCTA_CATALOG = [
    # --- SEED CHAMPION ZCTAs (High existing GA4 conversion & volume) ---
    {
        "zcta": "94043", "geo_name": "Mountain View, CA", "city": "Mountain View", "state": "California", "state_code": "CA",
        "county": "Santa Clara County", "admin1_id": "ChIJPV4oX_65j4ARVW8IJ6IJUYs", "admin2_id": "ChIJwR3g9PG3j4AR62h1ZyT4tM0",
        "lat": 37.4056, "lng": -122.0775, "is_seed_champion": True, "archetype": "tech_affluent_hub",
        "dominant_category": "Electronics", "paid_saturation": 0.68,
        "store_id": "STR-BAY-01", "store_name": "Google Store Mountain View", "store_dist_mi": 1.8, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.96, "search_home": 0.82, "search_fitness": 0.88, "maps_retail": 0.84, "maps_commuter": 0.94, "weather_warm": 0.82, "weather_friction": 0.12}
    },
    {
        "zcta": "94301", "geo_name": "Palo Alto, CA", "city": "Mountain View", "state": "California", "state_code": "CA",
        "county": "Santa Clara County", "admin1_id": "ChIJPV4oX_65j4ARVW8IJ6IJUYs", "admin2_id": "ChIJwR3g9PG3j4AR62h1ZyT4tM0",
        "lat": 37.4419, "lng": -122.1430, "is_seed_champion": True, "archetype": "tech_affluent_hub",
        "dominant_category": "Smart Home", "paid_saturation": 0.64,
        "store_id": "STR-BAY-02", "store_name": "Stanford Shopping Center Hub", "store_dist_mi": 2.4, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.93, "search_home": 0.94, "search_fitness": 0.90, "maps_retail": 0.89, "maps_commuter": 0.86, "weather_warm": 0.83, "weather_friction": 0.11}
    },
    {
        "zcta": "10012", "geo_name": "New York (SoHo), NY", "city": "New York", "state": "New York", "state_code": "NY",
        "county": "New York County", "admin1_id": "ChIJqaUj8fBLzEwRZ5UY3sHGz90", "admin2_id": "ChIJOwg_06VPwokRYv534QaPC8g",
        "lat": 40.7255, "lng": -73.9983, "is_seed_champion": True, "archetype": "urban_flagship_corridor",
        "dominant_category": "Wearables", "paid_saturation": 0.74,
        "store_id": "STR-NYC-01", "store_name": "Google Store Chelsea NYC", "store_dist_mi": 1.4, "dtc_warehouse_id": "WH-EAST-EDISON",
        "pdi_profile": {"search_tech": 0.91, "search_home": 0.68, "search_fitness": 0.95, "maps_retail": 0.98, "maps_commuter": 0.97, "weather_warm": 0.55, "weather_friction": 0.28}
    },
    {
        "zcta": "10013", "geo_name": "New York (Tribeca), NY", "city": "New York", "state": "New York", "state_code": "NY",
        "county": "New York County", "admin1_id": "ChIJqaUj8fBLzEwRZ5UY3sHGz90", "admin2_id": "ChIJOwg_06VPwokRYv534QaPC8g",
        "lat": 40.7195, "lng": -74.0054, "is_seed_champion": True, "archetype": "urban_flagship_corridor",
        "dominant_category": "Audio", "paid_saturation": 0.71,
        "store_id": "STR-NYC-01", "store_name": "Google Store Chelsea NYC", "store_dist_mi": 1.9, "dtc_warehouse_id": "WH-EAST-EDISON",
        "pdi_profile": {"search_tech": 0.90, "search_home": 0.74, "search_fitness": 0.92, "maps_retail": 0.95, "maps_commuter": 0.94, "weather_warm": 0.55, "weather_friction": 0.29}
    },
    {
        "zcta": "78701", "geo_name": "Austin (Downtown), TX", "city": "Austin", "state": "Texas", "state_code": "TX",
        "county": "Travis County", "admin1_id": "ChIJSTKCCzZwQIYRPN4IGI8c6xY", "admin2_id": "ChIJLwPMoJm1RIYRetVp1EtGm10",
        "lat": 30.2711, "lng": -97.7437, "is_seed_champion": True, "archetype": "sunbelt_tech_growth",
        "dominant_category": "Electronics", "paid_saturation": 0.59,
        "store_id": "STR-ATX-01", "store_name": "Austin Congress Flagship", "store_dist_mi": 1.2, "dtc_warehouse_id": "WH-SOUTH-DFW",
        "pdi_profile": {"search_tech": 0.92, "search_home": 0.85, "search_fitness": 0.89, "maps_retail": 0.91, "maps_commuter": 0.88, "weather_warm": 0.92, "weather_friction": 0.16}
    },
    {
        "zcta": "78758", "geo_name": "Austin (The Domain), TX", "city": "Austin", "state": "Texas", "state_code": "TX",
        "county": "Travis County", "admin1_id": "ChIJSTKCCzZwQIYRPN4IGI8c6xY", "admin2_id": "ChIJLwPMoJm1RIYRetVp1EtGm10",
        "lat": 30.3997, "lng": -97.7214, "is_seed_champion": True, "archetype": "sunbelt_tech_growth",
        "dominant_category": "Smart Home", "paid_saturation": 0.56,
        "store_id": "STR-ATX-02", "store_name": "Domain Northside Experience", "store_dist_mi": 0.9, "dtc_warehouse_id": "WH-SOUTH-DFW",
        "pdi_profile": {"search_tech": 0.89, "search_home": 0.91, "search_fitness": 0.86, "maps_retail": 0.93, "maps_commuter": 0.85, "weather_warm": 0.91, "weather_friction": 0.15}
    },

    # --- CANDIDATE LOOKALIKE EXPANSION & OMNICHANNEL ZCTAs ---
    {
        "zcta": "98004", "geo_name": "Bellevue (Downtown), WA", "city": "Bellevue", "state": "Washington", "state_code": "WA",
        "county": "King County", "admin1_id": "ChIJ-bDD5__lhVQRuvNfbGh4QpQ", "admin2_id": "ChIJN3X2g7JrkFQRe432a3R0E9Q",
        "lat": 47.6101, "lng": -122.2015, "is_seed_champion": False, "archetype": "tech_affluent_hub",
        "dominant_category": "Electronics", "paid_saturation": 0.11,
        "store_id": "STR-SEA-01", "store_name": "Bellevue Square Partner Hub", "store_dist_mi": 1.5, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.95, "search_home": 0.89, "search_fitness": 0.87, "maps_retail": 0.90, "maps_commuter": 0.91, "weather_warm": 0.48, "weather_friction": 0.42}
    },
    {
        "zcta": "94086", "geo_name": "Sunnyvale, CA", "city": "Mountain View", "state": "California", "state_code": "CA",
        "county": "Santa Clara County", "admin1_id": "ChIJPV4oX_65j4ARVW8IJ6IJUYs", "admin2_id": "ChIJwR3g9PG3j4AR62h1ZyT4tM0",
        "lat": 37.3718, "lng": -122.0260, "is_seed_champion": False, "archetype": "tech_affluent_hub",
        "dominant_category": "Electronics", "paid_saturation": 0.14,
        "store_id": "STR-BAY-01", "store_name": "Google Store Mountain View", "store_dist_mi": 4.2, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.95, "search_home": 0.86, "search_fitness": 0.85, "maps_retail": 0.82, "maps_commuter": 0.92, "weather_warm": 0.82, "weather_friction": 0.12}
    },
    {
        "zcta": "95014", "geo_name": "Cupertino, CA", "city": "Mountain View", "state": "California", "state_code": "CA",
        "county": "Santa Clara County", "admin1_id": "ChIJPV4oX_65j4ARVW8IJ6IJUYs", "admin2_id": "ChIJwR3g9PG3j4AR62h1ZyT4tM0",
        "lat": 37.3230, "lng": -122.0322, "is_seed_champion": False, "archetype": "tech_affluent_hub",
        "dominant_category": "Wearables", "paid_saturation": 0.09,
        "store_id": "STR-BAY-01", "store_name": "Google Store Mountain View", "store_dist_mi": 7.6, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.94, "search_home": 0.91, "search_fitness": 0.89, "maps_retail": 0.85, "maps_commuter": 0.89, "weather_warm": 0.84, "weather_friction": 0.11}
    },
    {
        "zcta": "02139", "geo_name": "Cambridge (Kendall Sq), MA", "city": "Cambridge", "state": "Massachusetts", "state_code": "MA",
        "county": "Middlesex County", "admin1_id": "ChIJbU60yXKb5IkR4E8f2a_N3gE", "admin2_id": "ChIJ_5K7yXKb5IkR8E8f2a_N3gE",
        "lat": 42.3647, "lng": -71.1032, "is_seed_champion": False, "archetype": "urban_flagship_corridor",
        "dominant_category": "Electronics", "paid_saturation": 0.08,
        "store_id": "STR-BOS-01", "store_name": "Newbury Street Boston Studio", "store_dist_mi": 2.1, "dtc_warehouse_id": "WH-EAST-EDISON",
        "pdi_profile": {"search_tech": 0.96, "search_home": 0.76, "search_fitness": 0.91, "maps_retail": 0.88, "maps_commuter": 0.95, "weather_warm": 0.49, "weather_friction": 0.36}
    },
    {
        "zcta": "11211", "geo_name": "Brooklyn (Williamsburg), NY", "city": "New York", "state": "New York", "state_code": "NY",
        "county": "Kings County", "admin1_id": "ChIJqaUj8fBLzEwRZ5UY3sHGz90", "admin2_id": "ChIJCSF8lBZEwokRhngABHRcdoI",
        "lat": 40.7132, "lng": -73.9562, "is_seed_champion": False, "archetype": "urban_flagship_corridor",
        "dominant_category": "Audio", "paid_saturation": 0.15,
        "store_id": "STR-BKN-01", "store_name": "Google Store Williamsburg", "store_dist_mi": 0.7, "dtc_warehouse_id": "WH-EAST-EDISON",
        "pdi_profile": {"search_tech": 0.89, "search_home": 0.72, "search_fitness": 0.94, "maps_retail": 0.96, "maps_commuter": 0.93, "weather_warm": 0.56, "weather_friction": 0.27}
    },
    {
        "zcta": "80302", "geo_name": "Boulder (Pearl St), CO", "city": "Boulder", "state": "Colorado", "state_code": "CO",
        "county": "Boulder County", "admin1_id": "ChIJt1YYm3QUQIcR_6eQSTGDVMc", "admin2_id": "ChIJ4cQ5m3QUQIcR_6eQSTGDVMc",
        "lat": 40.0150, "lng": -105.2705, "is_seed_champion": False, "archetype": "sunbelt_tech_growth",
        "dominant_category": "Wearables", "paid_saturation": 0.07,
        "store_id": "STR-DEN-01", "store_name": "Denver Cherry Creek Hub", "store_dist_mi": 26.5, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.90, "search_home": 0.88, "search_fitness": 0.98, "maps_retail": 0.84, "maps_commuter": 0.81, "weather_warm": 0.62, "weather_friction": 0.38}
    },
    {
        "zcta": "60607", "geo_name": "Chicago (Fulton Market), IL", "city": "Chicago", "state": "Illinois", "state_code": "IL",
        "county": "Cook County", "admin1_id": "ChIJGSZubzgtC4gRVlkRZFCCFX8", "admin2_id": "ChIJ7cv00DwsDogRAMDACa2m4K8",
        "lat": 41.8827, "lng": -87.6531, "is_seed_champion": False, "archetype": "urban_flagship_corridor",
        "dominant_category": "Electronics", "paid_saturation": 0.12,
        "store_id": "STR-CHI-01", "store_name": "Chicago Fulton Market Store", "store_dist_mi": 0.8, "dtc_warehouse_id": "WH-MIDWEST-ORD",
        "pdi_profile": {"search_tech": 0.91, "search_home": 0.81, "search_fitness": 0.89, "maps_retail": 0.93, "maps_commuter": 0.94, "weather_warm": 0.46, "weather_friction": 0.48}
    },
    {
        "zcta": "75024", "geo_name": "Plano (Legacy West), TX", "city": "Plano", "state": "Texas", "state_code": "TX",
        "county": "Collin County", "admin1_id": "ChIJSTKCCzZwQIYRPN4IGI8c6xY", "admin2_id": "ChIJv3X2g7JrkFQRe432a3R0E9Q",
        "lat": 33.0778, "lng": -96.8190, "is_seed_champion": False, "archetype": "sunbelt_tech_growth",
        "dominant_category": "Smart Home", "paid_saturation": 0.10,
        "store_id": "STR-DFW-01", "store_name": "Legacy West Retail Showcase", "store_dist_mi": 1.6, "dtc_warehouse_id": "WH-SOUTH-DFW",
        "pdi_profile": {"search_tech": 0.88, "search_home": 0.95, "search_fitness": 0.86, "maps_retail": 0.90, "maps_commuter": 0.87, "weather_warm": 0.90, "weather_friction": 0.17}
    },
    {
        "zcta": "90401", "geo_name": "Santa Monica, CA", "city": "Santa Monica", "state": "California", "state_code": "CA",
        "county": "Los Angeles County", "admin1_id": "ChIJPV4oX_65j4ARVW8IJ6IJUYs", "admin2_id": "ChIJE9on3F3HwoAR9AhGJW_fL-I",
        "lat": 34.0195, "lng": -118.4912, "is_seed_champion": False, "archetype": "urban_flagship_corridor",
        "dominant_category": "Wearables", "paid_saturation": 0.16,
        "store_id": "STR-LAX-01", "store_name": "Third Street Promenade Hub", "store_dist_mi": 1.1, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.91, "search_home": 0.83, "search_fitness": 0.96, "maps_retail": 0.95, "maps_commuter": 0.90, "weather_warm": 0.94, "weather_friction": 0.08}
    },
    {
        "zcta": "98101", "geo_name": "Seattle (Downtown / SLU), WA", "city": "Seattle", "state": "Washington", "state_code": "WA",
        "county": "King County", "admin1_id": "ChIJ-bDD5__lhVQRuvNfbGh4QpQ", "admin2_id": "ChIJN3X2g7JrkFQRe432a3R0E9Q",
        "lat": 47.6105, "lng": -122.3344, "is_seed_champion": False, "archetype": "tech_affluent_hub",
        "dominant_category": "Audio", "paid_saturation": 0.18,
        "store_id": "STR-SEA-01", "store_name": "Bellevue Square Partner Hub", "store_dist_mi": 9.8, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.94, "search_home": 0.79, "search_fitness": 0.88, "maps_retail": 0.91, "maps_commuter": 0.93, "weather_warm": 0.47, "weather_friction": 0.46}
    },
    {
        "zcta": "92618", "geo_name": "Irvine (Spectrum), CA", "city": "Irvine", "state": "California", "state_code": "CA",
        "county": "Orange County", "admin1_id": "ChIJPV4oX_65j4ARVW8IJ6IJUYs", "admin2_id": "ChIJZc0I3F3HwoAR9AhGJW_fL-I",
        "lat": 33.6584, "lng": -117.7376, "is_seed_champion": False, "archetype": "tech_affluent_hub",
        "dominant_category": "Smart Home", "paid_saturation": 0.09,
        "store_id": "STR-LAX-02", "store_name": "Irvine Spectrum Tech Lounge", "store_dist_mi": 2.0, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.91, "search_home": 0.93, "search_fitness": 0.89, "maps_retail": 0.91, "maps_commuter": 0.86, "weather_warm": 0.93, "weather_friction": 0.09}
    },
    {
        "zcta": "30309", "geo_name": "Atlanta (Midtown), GA", "city": "Atlanta", "state": "Georgia", "state_code": "GA",
        "county": "Fulton County", "admin1_id": "ChIJV4FfHcU28YgR5xBP7BC8hGY", "admin2_id": "ChIJ69Pk6jdZwokR5xBP7BC8hGY",
        "lat": 33.7889, "lng": -84.3841, "is_seed_champion": False, "archetype": "sunbelt_tech_growth",
        "dominant_category": "Electronics", "paid_saturation": 0.11,
        "store_id": "STR-ATL-01", "store_name": "Ponce City Market Showcase", "store_dist_mi": 2.3, "dtc_warehouse_id": "WH-SOUTH-DFW",
        "pdi_profile": {"search_tech": 0.89, "search_home": 0.86, "search_fitness": 0.87, "maps_retail": 0.90, "maps_commuter": 0.89, "weather_warm": 0.86, "weather_friction": 0.21}
    },
    {
        "zcta": "85251", "geo_name": "Scottsdale (Old Town), AZ", "city": "Scottsdale", "state": "Arizona", "state_code": "AZ",
        "county": "Maricopa County", "admin1_id": "ChIJaxhMy-sIK4cRcc3Bf7EnOUI", "admin2_id": "ChIJy3mhUO0SK4cRcc3Bf7EnOUI",
        "lat": 33.4942, "lng": -111.9261, "is_seed_champion": False, "archetype": "sunbelt_tech_growth",
        "dominant_category": "Smart Home", "paid_saturation": 0.08,
        "store_id": "STR-PHX-01", "store_name": "Scottsdale Fashion Square Hub", "store_dist_mi": 1.3, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.86, "search_home": 0.94, "search_fitness": 0.90, "maps_retail": 0.92, "maps_commuter": 0.83, "weather_warm": 0.97, "weather_friction": 0.24}
    },
    {
        "zcta": "27601", "geo_name": "Raleigh (Research Triangle), NC", "city": "Raleigh", "state": "North Carolina", "state_code": "NC",
        "county": "Wake County", "admin1_id": "ChIJgRo4_MQfVIgRZNFDv-ZQRog", "admin2_id": "ChIJ9Ro4_MQfVIgRZNFDv-ZQRog",
        "lat": 35.7796, "lng": -78.6382, "is_seed_champion": False, "archetype": "sunbelt_tech_growth",
        "dominant_category": "Apparel", "paid_saturation": 0.06,
        "store_id": "STR-ATL-01", "store_name": "Ponce City Market Showcase", "store_dist_mi": 355.0, "dtc_warehouse_id": "WH-EAST-EDISON",
        "pdi_profile": {"search_tech": 0.92, "search_home": 0.89, "search_fitness": 0.86, "maps_retail": 0.81, "maps_commuter": 0.85, "weather_warm": 0.80, "weather_friction": 0.19}
    },
    {
        "zcta": "20190", "geo_name": "Reston (Tech Corridor), VA", "city": "Reston", "state": "Virginia", "state_code": "VA",
        "county": "Fairfax County", "admin1_id": "ChIJzbK8vXDWTIgRlaZGt0lBTsA", "admin2_id": "ChIJ1bK8vXDWTIgRlaZGt0lBTsA",
        "lat": 38.9586, "lng": -77.3570, "is_seed_champion": False, "archetype": "tech_affluent_hub",
        "dominant_category": "Smart Home", "paid_saturation": 0.08,
        "store_id": "STR-DCA-01", "store_name": "Tysons Corner Tech Gallery", "store_dist_mi": 6.4, "dtc_warehouse_id": "WH-EAST-EDISON",
        "pdi_profile": {"search_tech": 0.93, "search_home": 0.92, "search_fitness": 0.85, "maps_retail": 0.85, "maps_commuter": 0.90, "weather_warm": 0.68, "weather_friction": 0.25}
    },
    {
        "zcta": "07030", "geo_name": "Hoboken, NJ", "city": "New York", "state": "New Jersey", "state_code": "NJ",
        "county": "Hudson County", "admin1_id": "ChIJn0AAnpX7wIkRjW0_-Ad70iw", "admin2_id": "ChIJp0AAnpX7wIkRjW0_-Ad70iw",
        "lat": 40.7440, "lng": -74.0324, "is_seed_champion": False, "archetype": "urban_flagship_corridor",
        "dominant_category": "Audio", "paid_saturation": 0.12,
        "store_id": "STR-NYC-01", "store_name": "Google Store Chelsea NYC", "store_dist_mi": 3.4, "dtc_warehouse_id": "WH-EAST-EDISON",
        "pdi_profile": {"search_tech": 0.89, "search_home": 0.78, "search_fitness": 0.92, "maps_retail": 0.89, "maps_commuter": 0.95, "weather_warm": 0.56, "weather_friction": 0.28}
    },
    {
        "zcta": "94107", "geo_name": "San Francisco (SoMa), CA", "city": "Mountain View", "state": "California", "state_code": "CA",
        "county": "San Francisco County", "admin1_id": "ChIJPV4oX_65j4ARVW8IJ6IJUYs", "admin2_id": "ChIJIQBpAG2ahYAR_6128GcTUEo",
        "lat": 37.7685, "lng": -122.3965, "is_seed_champion": False, "archetype": "tech_affluent_hub",
        "dominant_category": "Apparel", "paid_saturation": 0.22,
        "store_id": "STR-SFO-01", "store_name": "SF Embarcadero Flagship", "store_dist_mi": 1.6, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.97, "search_home": 0.75, "search_fitness": 0.91, "maps_retail": 0.92, "maps_commuter": 0.96, "weather_warm": 0.70, "weather_friction": 0.18}
    },
    {
        "zcta": "95110", "geo_name": "San Jose (Downtown), CA", "city": "Mountain View", "state": "California", "state_code": "CA",
        "county": "Santa Clara County", "admin1_id": "ChIJPV4oX_65j4ARVW8IJ6IJUYs", "admin2_id": "ChIJwR3g9PG3j4AR62h1ZyT4tM0",
        "lat": 37.3382, "lng": -121.8863, "is_seed_champion": False, "archetype": "tech_affluent_hub",
        "dominant_category": "Merchandise", "paid_saturation": 0.15,
        "store_id": "STR-BAY-01", "store_name": "Google Store Mountain View", "store_dist_mi": 11.8, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.91, "search_home": 0.84, "search_fitness": 0.84, "maps_retail": 0.83, "maps_commuter": 0.89, "weather_warm": 0.84, "weather_friction": 0.12}
    },
    {
        "zcta": "02116", "geo_name": "Boston (Back Bay), MA", "city": "Boston", "state": "Massachusetts", "state_code": "MA",
        "county": "Suffolk County", "admin1_id": "ChIJbU60yXKb5IkR4E8f2a_N3gE", "admin2_id": "ChIJGzE9DS1l44kRoOhiASS_fHg",
        "lat": 42.3503, "lng": -71.0772, "is_seed_champion": False, "archetype": "urban_flagship_corridor",
        "dominant_category": "Wearables", "paid_saturation": 0.14,
        "store_id": "STR-BOS-01", "store_name": "Newbury Street Boston Studio", "store_dist_mi": 0.5, "dtc_warehouse_id": "WH-EAST-EDISON",
        "pdi_profile": {"search_tech": 0.88, "search_home": 0.77, "search_fitness": 0.93, "maps_retail": 0.96, "maps_commuter": 0.93, "weather_warm": 0.49, "weather_friction": 0.37}
    },
    {
        "zcta": "80206", "geo_name": "Denver (Cherry Creek), CO", "city": "Denver", "state": "Colorado", "state_code": "CO",
        "county": "Denver County", "admin1_id": "ChIJt1YYm3QUQIcR_6eQSTGDVMc", "admin2_id": "ChIJzxcfI6qAa4cR1jaKJ_j0jhE",
        "lat": 39.7209, "lng": -104.9535, "is_seed_champion": False, "archetype": "sunbelt_tech_growth",
        "dominant_category": "Smart Home", "paid_saturation": 0.10,
        "store_id": "STR-DEN-01", "store_name": "Denver Cherry Creek Hub", "store_dist_mi": 0.9, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.86, "search_home": 0.91, "search_fitness": 0.94, "maps_retail": 0.91, "maps_commuter": 0.84, "weather_warm": 0.64, "weather_friction": 0.34}
    },
    {
        "zcta": "33131", "geo_name": "Miami (Brickell), FL", "city": "Miami", "state": "Florida", "state_code": "FL",
        "county": "Miami-Dade County", "admin1_id": "ChIJvypWkWV2wYgR0E7HW9MTLvc", "admin2_id": "ChIJEcHIDqKw2YgRZU-t3XHylv8",
        "lat": 25.7617, "lng": -80.1918, "is_seed_champion": False, "archetype": "urban_flagship_corridor",
        "dominant_category": "Wearables", "paid_saturation": 0.13,
        "store_id": "STR-MIA-01", "store_name": "Miami Design District Lounge", "store_dist_mi": 3.8, "dtc_warehouse_id": "WH-SOUTH-DFW",
        "pdi_profile": {"search_tech": 0.85, "search_home": 0.79, "search_fitness": 0.95, "maps_retail": 0.94, "maps_commuter": 0.89, "weather_warm": 0.96, "weather_friction": 0.26}
    },
    {
        "zcta": "75201", "geo_name": "Dallas (Arts District / Uptown), TX", "city": "Austin", "state": "Texas", "state_code": "TX",
        "county": "Dallas County", "admin1_id": "ChIJSTKCCzZwQIYRPN4IGI8c6xY", "admin2_id": "ChIJS5dFe_cZTIYRj2dH9qSb78k",
        "lat": 32.7876, "lng": -96.7985, "is_seed_champion": False, "archetype": "sunbelt_tech_growth",
        "dominant_category": "Electronics", "paid_saturation": 0.14,
        "store_id": "STR-DFW-01", "store_name": "Legacy West Retail Showcase", "store_dist_mi": 18.5, "dtc_warehouse_id": "WH-SOUTH-DFW",
        "pdi_profile": {"search_tech": 0.87, "search_home": 0.86, "search_fitness": 0.88, "maps_retail": 0.91, "maps_commuter": 0.90, "weather_warm": 0.90, "weather_friction": 0.18}
    },
    {
        "zcta": "60201", "geo_name": "Evanston (North Shore), IL", "city": "Chicago", "state": "Illinois", "state_code": "IL",
        "county": "Cook County", "admin1_id": "ChIJGSZubzgtC4gRVlkRZFCCFX8", "admin2_id": "ChIJ7cv00DwsDogRAMDACa2m4K8",
        "lat": 42.0451, "lng": -87.6877, "is_seed_champion": False, "archetype": "suburban_commuter_weather",
        "dominant_category": "Smart Home", "paid_saturation": 0.05,
        "store_id": "STR-CHI-01", "store_name": "Chicago Fulton Market Store", "store_dist_mi": 13.8, "dtc_warehouse_id": "WH-MIDWEST-ORD",
        "pdi_profile": {"search_tech": 0.84, "search_home": 0.93, "search_fitness": 0.82, "maps_retail": 0.72, "maps_commuter": 0.76, "weather_warm": 0.42, "weather_friction": 0.56}
    },
    {
        "zcta": "55401", "geo_name": "Minneapolis (North Loop), MN", "city": "Minneapolis", "state": "Minnesota", "state_code": "MN",
        "county": "Hennepin County", "admin1_id": "ChIJm6M5m3QUQIcR_6eQSTGDVMc", "admin2_id": "ChIJn6M5m3QUQIcR_6eQSTGDVMc",
        "lat": 44.9846, "lng": -93.2712, "is_seed_champion": False, "archetype": "suburban_commuter_weather",
        "dominant_category": "Smart Home", "paid_saturation": 0.06,
        "store_id": "STR-MSP-01", "store_name": "Mall of America Partner Kiosk", "store_dist_mi": 10.4, "dtc_warehouse_id": "WH-MIDWEST-ORD",
        "pdi_profile": {"search_tech": 0.86, "search_home": 0.94, "search_fitness": 0.85, "maps_retail": 0.78, "maps_commuter": 0.82, "weather_warm": 0.34, "weather_friction": 0.64}
    },
    {
        "zcta": "97209", "geo_name": "Portland (Pearl District), OR", "city": "Portland", "state": "Oregon", "state_code": "OR",
        "county": "Multnomah County", "admin1_id": "ChIJVWqfm3QUQIcR_6eQSTGDVMc", "admin2_id": "ChIJWWqfm3QUQIcR_6eQSTGDVMc",
        "lat": 45.5290, "lng": -122.6845, "is_seed_champion": False, "archetype": "tech_affluent_hub",
        "dominant_category": "Apparel", "paid_saturation": 0.07,
        "store_id": "STR-PDX-01", "store_name": "Pioneer Place Experience", "store_dist_mi": 1.1, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.90, "search_home": 0.83, "search_fitness": 0.91, "maps_retail": 0.87, "maps_commuter": 0.86, "weather_warm": 0.52, "weather_friction": 0.44}
    },
    {
        "zcta": "84101", "geo_name": "Salt Lake City (Silicon Slopes), UT", "city": "Salt Lake City", "state": "Utah", "state_code": "UT",
        "county": "Salt Lake County", "admin1_id": "ChIJzfkTj3QUQIcR_6eQSTGDVMc", "admin2_id": "ChIJ0fkTj3QUQIcR_6eQSTGDVMc",
        "lat": 40.7608, "lng": -111.8910, "is_seed_champion": False, "archetype": "sunbelt_tech_growth",
        "dominant_category": "Wearables", "paid_saturation": 0.05,
        "store_id": "STR-SLC-01", "store_name": "City Creek Tech Studio", "store_dist_mi": 1.4, "dtc_warehouse_id": "WH-WEST-RENO",
        "pdi_profile": {"search_tech": 0.91, "search_home": 0.89, "search_fitness": 0.95, "maps_retail": 0.85, "maps_commuter": 0.84, "weather_warm": 0.60, "weather_friction": 0.35}
    },
]

# City-to-ZCTA Crosswalk for Tier 3 Multi-Signal Geo Resolution
CITY_TO_ZCTA_CROSSWALK = [
    {"city": "Mountain View", "region": "California", "zcta": "94043", "bucket_start": 0, "bucket_end": 39, "pop_weight": 0.40},
    {"city": "Mountain View", "region": "California", "zcta": "94301", "bucket_start": 40, "bucket_end": 69, "pop_weight": 0.30},
    {"city": "Mountain View", "region": "California", "zcta": "94086", "bucket_start": 70, "bucket_end": 84, "pop_weight": 0.15},
    {"city": "Mountain View", "region": "California", "zcta": "95014", "bucket_start": 85, "bucket_end": 94, "pop_weight": 0.10},
    {"city": "Mountain View", "region": "California", "zcta": "94107", "bucket_start": 95, "bucket_end": 99, "pop_weight": 0.05},
    {"city": "New York", "region": "New York", "zcta": "10012", "bucket_start": 0, "bucket_end": 44, "pop_weight": 0.45},
    {"city": "New York", "region": "New York", "zcta": "10013", "bucket_start": 45, "bucket_end": 79, "pop_weight": 0.35},
    {"city": "New York", "region": "New York", "zcta": "11211", "bucket_start": 80, "bucket_end": 91, "pop_weight": 0.12},
    {"city": "New York", "region": "New York", "zcta": "07030", "bucket_start": 92, "bucket_end": 99, "pop_weight": 0.08},
    {"city": "Austin", "region": "Texas", "zcta": "78701", "bucket_start": 0, "bucket_end": 49, "pop_weight": 0.50},
    {"city": "Austin", "region": "Texas", "zcta": "78758", "bucket_start": 50, "bucket_end": 84, "pop_weight": 0.35},
    {"city": "Austin", "region": "Texas", "zcta": "75024", "bucket_start": 85, "bucket_end": 93, "pop_weight": 0.09},
    {"city": "Austin", "region": "Texas", "zcta": "75201", "bucket_start": 94, "bucket_end": 99, "pop_weight": 0.06},
]


def deterministic_rng(seed_str: str) -> random.Random:
    h = int(hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(h)


def build_330d_pdi_embedding(zcta_meta: Dict[str, Any]) -> List[float]:
    """
    Generates a realistic 330-dimensional PDI embedding vector:
      - Indices 0..127   (128 dims): Aggregated Search Trends
      - Indices 128..255 (128 dims): Maps & Busyness (POIs, foot traffic, built env)
      - Indices 256..329 (74 dims) : Weather & Air Quality
    Structured around latent factors so cosine similarity across subspaces reflects true market DNA.
    """
    rng = deterministic_rng(f"pdi_330d_{zcta_meta['zcta']}")
    prof = zcta_meta["pdi_profile"]
    vec: List[float] = []

    # 1. Search Trends Subspace (0..127)
    for i in range(128):
        phase = (i / 128.0) * math.pi * 2.0
        if i < 45:
            # Tech & Electronics Search Intent
            base = prof["search_tech"] * math.cos(phase * 1.5) + 0.35 * prof["search_home"] * math.sin(phase)
        elif i < 90:
            # Smart Home & Lifestyle Search Intent
            base = prof["search_home"] * math.sin(phase * 1.2) + 0.30 * prof["search_tech"] * math.cos(phase)
        else:
            # Wearables, Fitness & Audio Search Intent
            base = prof["search_fitness"] * math.cos(phase * 2.0) + 0.25 * prof["search_tech"]
        noise = rng.gauss(0.0, 0.055)
        vec.append(round(base + noise, 5))

    # 2. Maps & Busyness Subspace (128..255)
    for i in range(128):
        phase = (i / 128.0) * math.pi * 2.0
        if i < 64:
            # Retail POI Density & Shopping Corridor Foot Traffic
            base = prof["maps_retail"] * math.cos(phase * 1.3) + 0.30 * prof["maps_commuter"] * math.sin(phase)
        else:
            # Daytime Commuter Influx & Built Environment Density
            base = prof["maps_commuter"] * math.sin(phase * 1.7) + 0.35 * prof["maps_retail"] * math.cos(phase)
        noise = rng.gauss(0.0, 0.055)
        vec.append(round(base + noise, 5))

    # 3. Weather & Air Quality Subspace (256..329)
    for i in range(74):
        phase = (i / 74.0) * math.pi * 2.0
        if i < 40:
            # Temperature & Sunbelt Climate Pattern
            base = prof["weather_warm"] * math.cos(phase) - 0.40 * prof["weather_friction"] * math.sin(phase)
        else:
            # Precipitation, Wind & Visit Friction
            base = (1.0 - prof["weather_friction"]) * math.sin(phase * 1.4) + 0.30 * prof["weather_warm"]
        noise = rng.gauss(0.0, 0.05)
        vec.append(round(base + noise, 5))

    assert len(vec) == 330
    return vec


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def mean_vector(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    n = float(len(vectors))
    return [round(sum(v[i] for v in vectors) / n, 6) for i in range(dim)]


def generate_sku_inventory_for_zcta(zcta_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Generates realistic Store + DTC inventory & GA4 demand velocity for each of the 8 SKUs
    in a given ZCTA, deliberately creating rich examples of:
      1. Healthy In-Store Stock -> IN_STORE_BOPIS_LIA ("In-Store Near You")
      2. Imminent Depletion Trap (moderate units, high GA4 + PDI burn) -> DTC_WAREHOUSE_SHIP
      3. High Weather Friction or Far Store -> DTC_WAREHOUSE_SHIP
      4. Dual Stock Constraint -> SUPPRESS_HOLD_SPEND
    """
    zcta = zcta_meta["zcta"]
    rng = deterministic_rng(f"inv_{zcta}")
    rows = []

    for idx, prod in enumerate(PRODUCTS):
        sku_id = prod["id"]
        # Assign deterministic scenario pattern per (zcta, sku) so every SKU & ZCTA has realistic variety
        scenario_roll = (int(zcta) + idx * 7) % 10

        base_daily_sales = round(rng.uniform(2.2, 5.8), 1)
        ga4_demand_vel = round(rng.uniform(0.35, 0.92), 2)
        if prod["category"] == zcta_meta["dominant_category"]:
            ga4_demand_vel = round(min(0.99, ga4_demand_vel + 0.18), 2)

        # If store is >20 miles away (e.g. Raleigh 27601 or Boulder 80302), local store pickup isn't primary
        far_store = zcta_meta["store_dist_mi"] > 15.0

        if far_store:
            store_units = rng.randint(4, 18)
            dtc_units = rng.randint(140, 480)
            scenario_note = "Store beyond 15mi radius — auto-routed to regional DTC hub"
        elif scenario_roll in (0, 1, 2, 3, 4):
            # Healthy local store stock -> In-Store Near You (unless weather friction is extreme)
            store_units = rng.randint(24, 68)
            dtc_units = rng.randint(120, 450)
            scenario_note = "Healthy local store inventory & active foot traffic"
        elif scenario_roll in (5, 6):
            # Imminent Depletion Trap: 9-15 units on shelf, but high GA4 demand + PDI foot traffic burns it in <2.5 days
            store_units = rng.randint(9, 15)
            base_daily_sales = round(rng.uniform(4.2, 6.5), 1)
            ga4_demand_vel = round(rng.uniform(0.78, 0.98), 2)
            dtc_units = rng.randint(160, 520)
            scenario_note = "Imminent Store Depletion Trap (high GA4 + PDI burn rate -> pre-emptively routed to DTC)"
        elif scenario_roll in (7, 8):
            # Local Store Out-of-Stock / Low Stock, Healthy DTC Warehouse
            store_units = rng.randint(0, 5)
            dtc_units = rng.randint(180, 600)
            scenario_note = "Local store depleted — seamlessly routed to DTC Ship-to-Home"
        else:
            # Both Local Store AND Central DTC Warehouse Constrained -> Hold / Suppress Spend
            store_units = rng.randint(0, 4)
            dtc_units = rng.randint(4, 18)
            scenario_note = "Omnichannel stock constraint — suppress paid SKU spend to protect ROAS"

        rows.append({
            "zcta": zcta,
            "item_id": sku_id,
            "item_name": prod["name"],
            "item_category": prod["category"],
            "unit_price_usd": prod["price"],
            "cogs_ratio": prod["cogs_ratio"],
            "store_id": zcta_meta["store_id"],
            "store_name": zcta_meta["store_name"],
            "distance_to_store_miles": zcta_meta["store_dist_mi"],
            "store_on_hand_units": store_units,
            "base_daily_store_sales": base_daily_sales,
            "dtc_warehouse_id": zcta_meta["dtc_warehouse_id"],
            "dtc_available_units": dtc_units,
            "ga4_local_demand_velocity": ga4_demand_vel,
            "scenario_note": scenario_note
        })
    return rows


def load_and_map_ga4_users(zcta_lookup: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Loads GA4 users from `../static/api/users.json` and maps each user to a 5-digit ZCTA
    using our 3-tier Multi-Signal Geo Resolution waterfall, aggregating real GA4 KPIs per ZCTA.
    """
    raw_users = []
    if os.path.exists(GA4_USERS_JSON):
        with open(GA4_USERS_JSON, "r", encoding="utf-8") as f:
            payload = json.load(f)
            raw_users = payload.get("users", [])

    seed_zctas = [z["zcta"] for z in ZCTA_CATALOG if z["is_seed_champion"]]
    candidate_zctas = [z["zcta"] for z in ZCTA_CATALOG if not z["is_seed_champion"]]

    # Track per-ZCTA GA4 funnel metrics
    zcta_stats: Dict[str, Dict[str, Any]] = {}
    for z in ZCTA_CATALOG:
        zcta_stats[z["zcta"]] = {
            "active_users": 0,
            "total_sessions": 0,
            "item_views": 0,
            "cart_additions": 0,
            "checkouts": 0,
            "purchases": 0,
            "total_revenue_usd": 0.0,
            "sum_propensity": 0.0,
            "tier1_count": 0,
            "tier2_count": 0,
            "tier3_count": 0,
        }

    enriched_users = []
    for idx, u in enumerate(raw_users):
        uid = str(u.get("user_pseudo_id", f"10928374.{idx}"))
        rng = deterministic_rng(uid)

        # 68% of existing GA4 traffic is in the 6 Seed Champion ZCTAs; 32% is organic/early traffic in Candidate ZCTAs
        is_purchase_or_high = u.get("total_purchases", 0) > 0 or u.get("propensity_score", 0.0) >= 0.55
        if is_purchase_or_high and rng.random() < 0.74:
            assigned_zcta = rng.choice(seed_zctas)
        elif rng.random() < 0.58:
            assigned_zcta = rng.choice(seed_zctas)
        else:
            assigned_zcta = rng.choice(candidate_zctas)

        # Assign Geo Resolution Tier based on user funnel depth
        if u.get("total_purchases", 0) > 0 or u.get("total_checkout_starts", 0) > 0:
            res_tier = "Tier 1: Event Param (Checkout / Store Locator ZIP)"
            zcta_stats[assigned_zcta]["tier1_count"] += 1
        elif not str(u.get("user_id", "")).startswith("10928374"):
            res_tier = "Tier 2: 1P User Property (postal_code)"
            zcta_stats[assigned_zcta]["tier2_count"] += 1
        else:
            res_tier = "Tier 3: City-to-ZCTA Crosswalk"
            zcta_stats[assigned_zcta]["tier3_count"] += 1

        st = zcta_stats[assigned_zcta]
        st["active_users"] += 1
        st["total_sessions"] += int(u.get("total_sessions", 1))
        st["item_views"] += int(u.get("total_item_views", 1))
        st["cart_additions"] += int(u.get("total_cart_additions", 0))
        st["checkouts"] += int(u.get("total_checkout_starts", 0))
        st["purchases"] += int(u.get("total_purchases", 0))
        st["total_revenue_usd"] = round(st["total_revenue_usd"] + float(u.get("total_historical_spend", 0.0)), 2)
        st["sum_propensity"] += float(u.get("propensity_score", 0.1))

        if len(enriched_users) < 250:
            zmeta = zcta_lookup[assigned_zcta]
            enriched_users.append({
                "user_pseudo_id": uid,
                "user_id": u.get("user_id", uid),
                "zcta": assigned_zcta,
                "geo_name": zmeta["geo_name"],
                "state_code": zmeta["state_code"],
                "geo_resolution_tier": res_tier,
                "top_category_affinity": u.get("top_category_affinity", "Electronics"),
                "avg_item_price_viewed": u.get("avg_item_price_viewed", 150.0),
                "propensity_score": u.get("propensity_score", 0.25),
                "personalized_discount_pct": u.get("personalized_discount_pct", 5.0),
                "coupon_code": u.get("coupon_code", "NUDGE50-1000"),
                "cohort_name": u.get("cohort_name", "Engaged Cart Hesitators"),
                "total_sessions": u.get("total_sessions", 1),
                "total_item_views": u.get("total_item_views", 1),
                "total_cart_additions": u.get("total_cart_additions", 0),
                "total_purchases": u.get("total_purchases", 0),
                "total_historical_spend": u.get("total_historical_spend", 0.0),
                "predicted_ltv_365d": u.get("predicted_ltv_365d", 180.0),
            })

    return enriched_users, zcta_stats


def build_datasets() -> Dict[str, Any]:
    os.makedirs(OUTPUT_API_DIR, exist_ok=True)
    os.makedirs(OUTPUT_PAYLOAD_DIR, exist_ok=True)
    os.makedirs(OUTPUT_BQ_JSONL_DIR, exist_ok=True)

    zcta_lookup = {z["zcta"]: z for z in ZCTA_CATALOG}
    enriched_users, zcta_ga4_stats = load_and_map_ga4_users(zcta_lookup)

    # 1. Generate 330-dim PDI Embeddings for all 32 ZCTAs
    pdi_records = {}
    for z in ZCTA_CATALOG:
        zcta = z["zcta"]
        vec330 = build_330d_pdi_embedding(z)
        vec_search = vec330[0:128]
        vec_maps = vec330[128:256]
        vec_weather = vec330[256:330]

        prof = z["pdi_profile"]
        pdi_records[zcta] = {
            "zcta": zcta,
            "geo_name": z["geo_name"],
            "city": z["city"],
            "state": z["state"],
            "state_code": z["state_code"],
            "county": z["county"],
            "administrative_area_level_1_id": z["admin1_id"],
            "administrative_area_level_2_id": z["admin2_id"],
            "lat": z["lat"],
            "lng": z["lng"],
            "is_seed_champion": z["is_seed_champion"],
            "archetype": z["archetype"],
            "dominant_category": z["dominant_category"],
            "paid_saturation_ratio": z["paid_saturation"],
            "store_id": z["store_id"],
            "store_name": z["store_name"],
            "distance_to_store_miles": z["store_dist_mi"],
            "dtc_warehouse_id": z["dtc_warehouse_id"],
            "pdi_search_intent_index": round((prof["search_tech"] + prof["search_home"] + prof["search_fitness"]) / 3.0, 3),
            "pdi_retail_busyness_index": round(0.60 * prof["maps_retail"] + 0.40 * prof["maps_commuter"], 3),
            "pdi_commuter_influx_index": round(prof["maps_commuter"], 3),
            "pdi_weather_warmth_index": round(prof["weather_warm"], 3),
            "pdi_weather_friction_index": round(prof["weather_friction"], 3),
            "vec_search_0_127": vec_search,
            "vec_maps_128_255": vec_maps,
            "vec_weather_256_329": vec_weather,
            "full_330d_embedding": vec330,
        }

    # 2. Compute Seed Centroid Vectors across the 6 Seed Champion ZCTAs
    seed_Search_vecs = [pdi_records[z["zcta"]]["vec_search_0_127"] for z in ZCTA_CATALOG if z["is_seed_champion"]]
    seed_Maps_vecs = [pdi_records[z["zcta"]]["vec_maps_128_255"] for z in ZCTA_CATALOG if z["is_seed_champion"]]
    seed_Weather_vecs = [pdi_records[z["zcta"]]["vec_weather_256_329"] for z in ZCTA_CATALOG if z["is_seed_champion"]]

    centroid_search = mean_vector(seed_Search_vecs)
    centroid_maps = mean_vector(seed_Maps_vecs)
    centroid_weather = mean_vector(seed_Weather_vecs)

    # 3. Assemble ZCTA Lookalike & Performance Table + Store/DTC Inventory Matrix
    zcta_rows = []
    all_inventory_rows = []

    for z in ZCTA_CATALOG:
        zcta = z["zcta"]
        p = pdi_records[zcta]
        st = zcta_ga4_stats[zcta]

        sim_search = round(cosine_similarity(p["vec_search_0_127"], centroid_search), 4)
        sim_maps = round(cosine_similarity(p["vec_maps_128_255"], centroid_maps), 4)
        sim_weather = round(cosine_similarity(p["vec_weather_256_329"], centroid_weather), 4)

        # Default weights: 45% Search, 40% Maps/Busyness, 15% Weather
        comp_sim = round(0.45 * sim_search + 0.40 * sim_maps + 0.15 * sim_weather, 4)
        whitespace_score = round(comp_sim * math.pow(max(0.10, 1.0 - p["paid_saturation_ratio"]), 0.65), 4)

        # Scale up sample counts (x11.2 to match full 13,465 BigQuery user corpus)
        scale_factor = 11.2
        active_users_scaled = max(12, int(round(st["active_users"] * scale_factor)))
        sessions_scaled = max(18, int(round(st["total_sessions"] * scale_factor)))
        purchases_scaled = int(round(st["purchases"] * scale_factor))
        revenue_scaled = round(st["total_revenue_usd"] * scale_factor, 2)

        if z["is_seed_champion"]:
            cvr = round(max(0.088, purchases_scaled / max(1, sessions_scaled)), 4)
            rev_per_user = round(max(68.0, revenue_scaled / max(1, active_users_scaled)), 2)
        else:
            cvr = round(min(0.065, max(0.018, purchases_scaled / max(1, sessions_scaled))), 4)
            rev_per_user = round(max(14.5, revenue_scaled / max(1, active_users_scaled)), 2)

        sku_inv = generate_sku_inventory_for_zcta(z)
        all_inventory_rows.extend(sku_inv)

        # Dominant resolution tier
        tier_counts = [
            ("Tier 1: Event Param (sGTM / Checkout)", st["tier1_count"]),
            ("Tier 2: 1P User Property", st["tier2_count"]),
            ("Tier 3: City-to-ZCTA Crosswalk", st["tier3_count"]),
        ]
        primary_tier = max(tier_counts, key=lambda x: x[1])[0]

        zcta_rows.append({
            "zcta": zcta,
            "geo_name": p["geo_name"],
            "city": p["city"],
            "state": p["state"],
            "state_code": p["state_code"],
            "county": p["county"],
            "administrative_area_level_1_id": p["administrative_area_level_1_id"],
            "administrative_area_level_2_id": p["administrative_area_level_2_id"],
            "lat": p["lat"],
            "lng": p["lng"],
            "is_seed_champion": p["is_seed_champion"],
            "archetype": p["archetype"],
            "dominant_category": p["dominant_category"],
            "primary_resolution_tier": primary_tier,
            "tier1_share": round(st["tier1_count"] / max(1, st["active_users"]), 2),
            "tier2_share": round(st["tier2_count"] / max(1, st["active_users"]), 2),
            "tier3_share": round(st["tier3_count"] / max(1, st["active_users"]), 2),
            "active_users": active_users_scaled,
            "total_sessions": sessions_scaled,
            "purchases": purchases_scaled,
            "total_revenue_usd": revenue_scaled,
            "conversion_rate": cvr,
            "revenue_per_user": rev_per_user,
            "paid_saturation_ratio": p["paid_saturation_ratio"],
            "sim_search_0_127": sim_search,
            "sim_maps_128_255": sim_maps,
            "sim_weather_256_329": sim_weather,
            "composite_pdi_similarity": comp_sim,
            "whitespace_opportunity_score": whitespace_score,
            "predicted_expansion_roas": round(1.8 + 3.4 * whitespace_score, 2),
            "pdi_search_intent_index": p["pdi_search_intent_index"],
            "pdi_retail_busyness_index": p["pdi_retail_busyness_index"],
            "pdi_commuter_influx_index": p["pdi_commuter_influx_index"],
            "pdi_weather_warmth_index": p["pdi_weather_warmth_index"],
            "pdi_weather_friction_index": p["pdi_weather_friction_index"],
            "pdi_profile": z["pdi_profile"],
            "store_id": p["store_id"],
            "store_name": p["store_name"],
            "distance_to_store_miles": p["distance_to_store_miles"],
            "dtc_warehouse_id": p["dtc_warehouse_id"],
            # Include compact 24-dim slice previews + full 330-dim embedding for real-time cosine similarity in UI
            "vec_search_0_127": p["vec_search_0_127"],
            "vec_maps_128_255": p["vec_maps_128_255"],
            "vec_weather_256_329": p["vec_weather_256_329"],
            "sku_inventory": {item["item_id"]: item for item in sku_inv},
        })

    # Write BigQuery-ready JSONL tables into `mock_bq_tables/`
    with open(os.path.join(OUTPUT_BQ_JSONL_DIR, "pdi_zcta_embeddings.jsonl"), "w", encoding="utf-8") as f:
        for zcta, rec in pdi_records.items():
            f.write(json.dumps({
                "geo_id": zcta,
                "geo_name": rec["geo_name"],
                "administrative_area_level_1_id": rec["administrative_area_level_1_id"],
                "administrative_area_level_1_name": rec["state"],
                "administrative_area_level_2_id": rec["administrative_area_level_2_id"],
                "administrative_area_level_2_name": rec["county"],
                "features": rec["full_330d_embedding"],
            }) + "\n")

    with open(os.path.join(OUTPUT_BQ_JSONL_DIR, "zcta_store_sku_inventory.jsonl"), "w", encoding="utf-8") as f:
        for row in all_inventory_rows:
            f.write(json.dumps(row) + "\n")

    with open(os.path.join(OUTPUT_BQ_JSONL_DIR, "city_to_zcta_crosswalk.jsonl"), "w", encoding="utf-8") as f:
        for row in CITY_TO_ZCTA_CROSSWALK:
            f.write(json.dumps(row) + "\n")

    # Write main API bundle for the web app (`static/api/pdi_geo_stock_data.json`)
    api_bundle = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "project_id": "ga4demo-503822",
        "dataset_id": "analytics_312456789",
        "total_ga4_users_mapped": 13465,
        "total_zctas": len(zcta_rows),
        "seed_champion_count": sum(1 for r in zcta_rows if r["is_seed_champion"]),
        "candidate_expansion_count": sum(1 for r in zcta_rows if not r["is_seed_champion"]),
        "products": PRODUCTS,
        "crosswalk": CITY_TO_ZCTA_CROSSWALK,
        "centroids": {
            "search_0_127": centroid_search,
            "maps_128_255": centroid_maps,
            "weather_256_329": centroid_weather,
        },
        "zctas": zcta_rows,
        "sample_users": enriched_users,
    }

    with open(os.path.join(OUTPUT_API_DIR, "pdi_geo_stock_data.json"), "w", encoding="utf-8") as f:
        json.dump(api_bundle, f)

    # Generate the 3 Downstream Activation Payloads
    generate_activation_payloads(zcta_rows, enriched_users)

    return api_bundle


def evaluate_sku_routing(zcta_row: Dict[str, Any], sku_inv: Dict[str, Any], min_edos: float = 3.5) -> Dict[str, Any]:
    """Computes Effective Days of Supply (eDOS) and 3-way routing decision for a (ZCTA, SKU) pair."""
    base_sales = sku_inv["base_daily_store_sales"]
    ga4_vel = sku_inv["ga4_local_demand_velocity"]
    busyness = zcta_row["pdi_retail_busyness_index"]
    weather_friction = zcta_row["pdi_weather_friction_index"]
    dist_mi = sku_inv["distance_to_store_miles"]
    store_units = sku_inv["store_on_hand_units"]
    dtc_units = sku_inv["dtc_available_units"]

    daily_burn = max(
        0.5,
        base_sales * (1.0 + 0.50 * ga4_vel) * (1.0 + 0.60 * busyness) * (1.0 - 0.25 * weather_friction)
    )
    edos = round(store_units / daily_burn, 1)
    visit_propensity = round(
        min(0.98, max(0.05, 0.65 * busyness + 0.35 * (1.0 - min(1.0, dist_mi / 25.0)) - 0.30 * weather_friction)),
        3
    )

    if store_units >= 8 and edos >= min_edos and dist_mi <= 15.0 and visit_propensity >= 0.42:
        decision = "IN_STORE_BOPIS_LIA"
        bid_modifier = "+35%"
        campaign_type = "Google Ads Local Inventory Ads (LIA) + BOPIS Radius Boost"
        headline = f"In Stock Near You ({zcta_row['zcta']}): Pick Up {sku_inv['item_name']} Today at {sku_inv['store_name']} ({store_units} Available)!"
        cta = "Reserve for 1-Hour Store Pickup"
    elif dtc_units >= 25:
        decision = "DTC_WAREHOUSE_SHIP"
        bid_modifier = "+20%" if not zcta_row["is_seed_champion"] else "+10%"
        campaign_type = f"DTC Shopping / PMax ({sku_inv['dtc_warehouse_id']}) — Store Extensions Suppressed"
        headline = f"Fast Direct Delivery to {zcta_row['geo_name']}: Get {sku_inv['item_name']} Shipped Free from Our DTC Hub!"
        cta = "Order Online — Free 2-Day Delivery"
    else:
        decision = "SUPPRESS_HOLD_SPEND"
        bid_modifier = "-100% (Paused)"
        campaign_type = "Pause Paid SKU Media (Prevent Stockout Ad Waste)"
        headline = f"{sku_inv['item_name']} Is High-Demand in {zcta_row['geo_name']} — Get Restock Alert & Explore Similar Favorites"
        cta = "Notify Me When Restocked"

    return {
        "predicted_daily_burn": round(daily_burn, 2),
        "effective_days_of_supply": edos,
        "in_store_visit_propensity": visit_propensity,
        "routing_channel_decision": decision,
        "bid_modifier": bid_modifier,
        "campaign_type": campaign_type,
        "headline": headline,
        "cta": cta,
    }


def generate_activation_payloads(zcta_rows: List[Dict[str, Any]], users: List[Dict[str, Any]]) -> None:
    """Writes sample Reverse-ETL activation payloads for Google Ads Geo/LIA, DTC Web, and GA4 MP."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 1. Google Ads Geo-Expansion & Local Inventory Ads (LIA) Payload
    ads_campaigns = []
    for z in zcta_rows:
        if z["is_seed_champion"] or z["composite_pdi_similarity"] >= 0.78:
            sku_inv = z["sku_inventory"]["PROD-101"]
            rt = evaluate_sku_routing(z, sku_inv)
            ads_campaigns.append({
                "location_criterion_zcta": f"US-{z['zcta']}",
                "geo_name": z["geo_name"],
                "use_case_a_role": "SEED_CHAMPION" if z["is_seed_champion"] else "PDI_LOOKALIKE_EXPANSION",
                "pdi_330d_cosine_similarity": z["composite_pdi_similarity"],
                "whitespace_opportunity_score": z["whitespace_opportunity_score"],
                "predicted_expansion_roas": z["predicted_expansion_roas"],
                "primary_sku_id": "PROD-101",
                "use_case_b_routing": rt["routing_channel_decision"],
                "local_store_id": z["store_id"],
                "local_store_on_hand": sku_inv["store_on_hand_units"],
                "effective_days_of_supply": rt["effective_days_of_supply"],
                "dtc_warehouse_available": sku_inv["dtc_available_units"],
                "google_ads_bid_adjustment": rt["bid_modifier"],
                "campaign_directive": rt["campaign_type"],
                "ad_customizer_headline": rt["headline"],
            })

    with open(os.path.join(OUTPUT_PAYLOAD_DIR, "google_ads_geo_lia_payload.json"), "w", encoding="utf-8") as f:
        json.dump({
            "target_platform": "Google Ads API v17 (LocationCriterionService + LocalInventoryAdFeed)",
            "generated_at": now_iso,
            "total_zctas_activated": len(ads_campaigns),
            "zcta_directives": ads_campaigns,
        }, f, indent=2)

    # 2. DTC Storefront & Omnichannel Personalization API Payload
    zcta_map = {z["zcta"]: z for z in zcta_rows}
    web_profiles = []
    for u in users[:50]:
        z = zcta_map[u["zcta"]]
        # Match user's top category to a hero SKU
        cat_skus = [p["id"] for p in PRODUCTS if p["category"] == u["top_category_affinity"]]
        hero_sku = cat_skus[0] if cat_skus else "PROD-101"
        sku_inv = z["sku_inventory"][hero_sku]
        rt = evaluate_sku_routing(z, sku_inv)
        web_profiles.append({
            "user_pseudo_id": u["user_pseudo_id"],
            "user_id": u["user_id"],
            "resolved_zcta": u["zcta"],
            "geo_resolution_tier": u["geo_resolution_tier"],
            "top_category_affinity": u["top_category_affinity"],
            "routed_sku_id": hero_sku,
            "routed_sku_name": sku_inv["item_name"],
            "fulfillment_routing": rt["routing_channel_decision"],
            "nearest_store_name": z["store_name"],
            "effective_days_of_supply": rt["effective_days_of_supply"],
            "ga4_1to1_discount_pct": u["personalized_discount_pct"],
            "ga4_coupon_code": u["coupon_code"],
            "personalized_hero_banner": rt["headline"],
            "personalized_cta": rt["cta"],
        })

    with open(os.path.join(OUTPUT_PAYLOAD_DIR, "dtc_web_personalization_payload.json"), "w", encoding="utf-8") as f:
        json.dump({
            "target_platform": "Edge Storefront Personalization API (Geo + Stock + 1:1 GA4)",
            "generated_at": now_iso,
            "profiles_count": len(web_profiles),
            "profiles": web_profiles,
        }, f, indent=2)

    # 3. GA4 Measurement Protocol Geo & Stock User Properties Payload
    mp_events = []
    for p in web_profiles[:30]:
        mp_events.append({
            "client_id": p["user_pseudo_id"],
            "user_id": p["user_id"],
            "user_properties": {
                "resolved_zcta": {"value": p["resolved_zcta"]},
                "pdi_geo_segment": {"value": "SEED_CHAMPION" if zcta_map[p["resolved_zcta"]]["is_seed_champion"] else "PDI_LOOKALIKE_EXPANSION"},
                "stock_routing_channel": {"value": p["fulfillment_routing"]},
                "nearest_store_edos": {"value": str(p["effective_days_of_supply"])},
                "personalized_offer_pct": {"value": f"{p['ga4_1to1_discount_pct']}%"},
            },
            "events": [{
                "name": "omnichannel_stock_route_assigned",
                "params": {
                    "zcta": p["resolved_zcta"],
                    "sku_id": p["routed_sku_id"],
                    "routing_decision": p["fulfillment_routing"],
                }
            }]
        })

    with open(os.path.join(OUTPUT_PAYLOAD_DIR, "ga4_measurement_protocol_geo_payload.json"), "w", encoding="utf-8") as f:
        json.dump({
            "target_platform": "GA4 Measurement Protocol (https://www.google-analytics.com/mp/collect)",
            "generated_at": now_iso,
            "batch_size": len(mp_events),
            "payloads": mp_events,
        }, f, indent=2)


def push_tables_to_bigquery(project_id: str, dataset_id: str, external_pdi_table: str = None) -> None:
    """Optionally uploads the generated PDI, Crosswalk, and Inventory tables into BigQuery."""
    try:
        from google.cloud import bigquery
    except ImportError:
        print("[!] google-cloud-bigquery not installed in active environment; skipping BigQuery upload.")
        return

    client = bigquery.Client(project=project_id)
    dataset_ref = f"{project_id}.{dataset_id}"

    tables_to_load = [
        ("pdi_zcta_embeddings", os.path.join(OUTPUT_BQ_JSONL_DIR, "pdi_zcta_embeddings.jsonl")),
        ("zcta_store_sku_inventory", os.path.join(OUTPUT_BQ_JSONL_DIR, "zcta_store_sku_inventory.jsonl")),
        ("city_to_zcta_crosswalk", os.path.join(OUTPUT_BQ_JSONL_DIR, "city_to_zcta_crosswalk.jsonl")),
    ]

    for table_name, jsonl_path in tables_to_load:
        if table_name == "pdi_zcta_embeddings" and external_pdi_table:
            print(f"[*] Using external live PDI BigQuery table: {external_pdi_table}")
            continue
        table_id = f"{dataset_ref}.{table_name}"
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=True,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        with open(jsonl_path, "rb") as source_file:
            job = client.load_table_from_file(source_file, table_id, job_config=job_config)
        job.result()
        print(f"[+] Loaded BigQuery table: {table_id}")


def main():
    parser = argparse.ArgumentParser(description="Generate PDI 330-dim embeddings + GA4 ZCTA + Stock Routing datasets.")
    parser.add_argument("--project_id", default="ga4demo-503822", help="GCP Project ID")
    parser.add_argument("--dataset_id", default="analytics_312456789", help="BigQuery Dataset ID")
    parser.add_argument("--pdi_table", default=None, help="Optional live BigQuery PDI table path (project.dataset.table)")
    parser.add_argument("--push_to_bq", action="store_true", help="Upload generated JSONL tables to BigQuery")
    args = parser.parse_args()

    bundle = build_datasets()
    print(f"[+] Generated PDI 330-dim embeddings & stock routing data for {bundle['total_zctas']} ZCTAs "
          f"({bundle['seed_champion_count']} Seed Champions, {bundle['candidate_expansion_count']} Lookalike Candidates).")
    print(f"[+] Saved static API bundle to: {os.path.join(OUTPUT_API_DIR, 'pdi_geo_stock_data.json')}")
    print(f"[+] Saved 3 activation payloads to: {OUTPUT_PAYLOAD_DIR}")

    if args.push_to_bq:
        push_tables_to_bigquery(args.project_id, args.dataset_id, args.pdi_table)


if __name__ == "__main__":
    main()
