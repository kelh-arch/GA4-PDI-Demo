#!/usr/bin/env python3
"""
Standalone Backend Server for the PDI + GA4 + Stock Inventory Command Center Demo.
Uses Python's built-in http.server so zero external web frameworks are required.

Endpoints:
  GET  /                         -> Serves static/index.html
  GET  /api/data                 -> Returns full PDI + GA4 + Stock dataset (static/api/pdi_geo_stock_data.json)
  GET  /api/payloads             -> Returns the 3 generated activation payloads (Google Ads, DTC Web, GA4 MP)
  GET  /api/docs                 -> Returns architecture markdown & BigQuery SQL pipeline text
  POST /api/simulate_lookalike   -> Dynamically recalculates Use Case A subspace-weighted cosine similarity
  POST /api/simulate_routing     -> Dynamically recalculates Use Case B eDOS & stock-aware routing decisions
"""

import argparse
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import math
import os
from urllib.parse import urlparse

from generate_pdi_stock_data import (
    build_datasets,
    cosine_similarity,
    evaluate_sku_routing,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_JSON_PATH = os.path.join(STATIC_DIR, "api", "pdi_geo_stock_data.json")
PAYLOAD_DIR = os.path.join(BASE_DIR, "activation_payloads")
SQL_PATH = os.path.join(BASE_DIR, "pdi_geo_inventory_queries.sql")
ARCH_PATH = os.path.join(BASE_DIR, "architecture_pdi_ga4_stock.md")

CACHED_DATA = None


def get_dataset():
  global CACHED_DATA
  if CACHED_DATA is None:
    if not os.path.exists(DATA_JSON_PATH):
      build_datasets()
    with open(DATA_JSON_PATH, "r", encoding="utf-8") as f:
      CACHED_DATA = json.load(f)
  return CACHED_DATA


class PDIGeoInventoryHandler(SimpleHTTPRequestHandler):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, directory=STATIC_DIR, **kwargs)

  def _send_json(self, payload, status=200):
    body = json.dumps(payload).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Access-Control-Allow-Origin", "*")
    self.end_headers()
    self.wfile.write(body)

  def do_OPTIONS(self):
    self.send_response(204)
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type")
    self.end_headers()

  def do_GET(self):
    parsed = urlparse(self.path)
    if parsed.path == "/api/data":
      self._send_json(get_dataset())
      return
    elif parsed.path == "/api/payloads":
      payloads = {}
      for fname in [
          "google_ads_geo_lia_payload.json",
          "dtc_web_personalization_payload.json",
          "ga4_measurement_protocol_geo_payload.json",
      ]:
        fpath = os.path.join(PAYLOAD_DIR, fname)
        if os.path.exists(fpath):
          with open(fpath, "r", encoding="utf-8") as f:
            payloads[fname] = json.load(f)
      self._send_json(payloads)
      return
    elif parsed.path == "/api/docs":
      sql_text = ""
      arch_text = ""
      if os.path.exists(SQL_PATH):
        with open(SQL_PATH, "r", encoding="utf-8") as f:
          sql_text = f.read()
      if os.path.exists(ARCH_PATH):
        with open(ARCH_PATH, "r", encoding="utf-8") as f:
          arch_text = f.read()
      self._send_json({"sql": sql_text, "architecture": arch_text})
      return
    return super().do_GET()

  def do_POST(self):
    parsed = urlparse(self.path)
    content_len = int(self.headers.get("Content-Length", 0))
    raw_body = self.rfile.read(content_len) if content_len > 0 else b"{}"
    try:
      params = json.loads(raw_body.decode("utf-8"))
    except Exception:
      params = {}

    data = get_dataset()

    if parsed.path == "/api/simulate_lookalike":
      w_search = float(params.get("w_search", 0.50))
      w_maps = float(params.get("w_maps", 0.35))
      w_weather = float(params.get("w_weather", 0.15))
      total_w = (w_search + w_maps + w_weather) or 1.0
      w_search, w_maps, w_weather = (
          w_search / total_w,
          w_maps / total_w,
          w_weather / total_w,
      )

      min_sim = float(params.get("min_similarity", 0.78))
      max_saturation = float(params.get("max_paid_saturation", 0.35))
      seed_filter = params.get("seed_zcta", "ALL")

      seeds = [
          z
          for z in data["zctas"]
          if z["is_seed_champion"]
          and (seed_filter == "ALL" or z["zcta"] == seed_filter)
      ]
      if not seeds:
        seeds = [z for z in data["zctas"] if z["is_seed_champion"]]

      candidates = []
      for z in data["zctas"]:
        if z["is_seed_champion"]:
          continue
        best_match = None
        best_score = -1.0
        for s in seeds:
          sim_s = cosine_similarity(
              z["vec_search_0_127"], s["vec_search_0_127"]
          )
          sim_m = cosine_similarity(z["vec_maps_128_255"], s["vec_maps_128_255"])
          sim_w = cosine_similarity(
              z["vec_weather_256_329"], s["vec_weather_256_329"]
          )
          composite = round(
              w_search * sim_s + w_maps * sim_m + w_weather * sim_w, 4
          )
          if composite > best_score:
            best_score = composite
            best_match = {
                "seed_zcta": s["zcta"],
                "seed_name": s["geo_name"],
                "sim_search": round(sim_s, 4),
                "sim_maps": round(sim_m, 4),
                "sim_weather": round(sim_w, 4),
                "composite_similarity": composite,
            }
        white_space_score = round(
            best_score
            * math.pow(max(0.10, 1.0 - z["paid_saturation_ratio"]), 0.65),
            4,
        )
        qualified = (best_score >= min_sim) and (
            z["paid_saturation_ratio"] <= max_saturation
        )
        candidates.append({
            "zcta": z["zcta"],
            "geo_name": z["geo_name"],
            "state": z["state"],
            "archetype": z["archetype"],
            "paid_saturation_ratio": z["paid_saturation_ratio"],
            "active_users": z["active_users"],
            "match": best_match,
            "white_space_opportunity_score": white_space_score,
            "qualified_for_expansion": qualified,
        })

      candidates.sort(
          key=lambda x: x["white_space_opportunity_score"], reverse=True
      )
      self._send_json({
          "weights_normalized": {
              "w_search": round(w_search, 3),
              "w_maps": round(w_maps, 3),
              "w_weather": round(w_weather, 3),
          },
          "qualified_count": sum(
              1 for c in candidates if c["qualified_for_expansion"]
          ),
          "candidates": candidates,
      })
      return

    elif parsed.path == "/api/simulate_routing":
      sku_id = params.get("item_id", "PROD-101")
      min_edos = float(params.get("min_edos_threshold", 3.5))

      results = []
      counts = {
          "IN_STORE_BOPIS_LIA": 0,
          "DTC_WAREHOUSE_SHIP": 0,
          "SUPPRESS_HOLD_SPEND": 0,
      }
      for z in data["zctas"]:
        sku_entry = z["sku_inventory"].get(
            sku_id, list(z["sku_inventory"].values())[0]
        )
        decision = evaluate_sku_routing(z, sku_entry, min_edos=min_edos)
        counts[decision["routing_channel_decision"]] += 1
        results.append({
            "zcta": z["zcta"],
            "geo_name": z["geo_name"],
            "state": z["state"],
            "is_seed_champion": z["is_seed_champion"],
            "sku": sku_entry,
            "routing": decision,
        })

      self._send_json({
          "item_id": sku_id,
          "summary_counts": counts,
          "zcta_routes": results,
      })
      return

    self._send_json({"error": "Unknown endpoint"}, status=404)


def run(port=8081):
  get_dataset()
  server_address = ("", port)
  httpd = HTTPServer(server_address, PDIGeoInventoryHandler)
  print(
      "\n🚀 PDI + GA4 + Stock Inventory Command Center running at:"
      f" http://localhost:{port}"
  )
  print(f"   Serving static assets from: {STATIC_DIR}")
  print(f"   API endpoints: /api/data, /api/payloads, /api/docs")
  print(
      "   Simulation POST endpoints: /api/simulate_lookalike,"
      " /api/simulate_routing\n"
  )
  httpd.serve_forever()


if __name__ == "__main__":
  parser = argparse.ArgumentParser(
      description="Run PDI + GA4 + Stock Demo Server"
  )
  parser.add_argument(
      "--port",
      type=int,
      default=8081,
      help="Port to run HTTP server on (default: 8081)",
  )
  args = parser.parse_args()
  run(port=args.port)
