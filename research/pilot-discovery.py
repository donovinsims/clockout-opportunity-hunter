#!/usr/bin/env python3
"""Build a bounded, evidence-preserving ten-business discovery pilot."""
import json, re, sqlite3, hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "pilot-discovery"
APPROVED = {"Roscoe", "Rockton", "Rockford", "South Beloit", "Loves Park", "Machesney Park", "Belvidere", "Beloit"}
SOCIAL = {"facebook.com", "instagram.com", "yelp.com", "yellowpages.com", "mapquest.com", "google.com", "bbb.org"}
FRANCHISE = ("roto-rooter", "farm & fleet", "farm and fleet", "window world", "feldco", "infinity exteriors", "greatwater", "butitta", "abc plumbing")

def norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())
def host(url):
    try: return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception: return ""
def town(address):
    m = re.search(r",\s*(Roscoe|Rockton|Rockford|South Beloit|Loves Park|Machesney Park|Belvidere|Beloit),\s*(IL|WI)\s+\d{5}", address or "", re.I)
    if not m: return None
    city, state = m.group(1), m.group(2)
    city = next((x for x in APPROVED if x.lower() == city.lower()), city)
    if city == "Beloit" and state.upper() != "WI": return None
    if city != "Beloit" and state.upper() != "IL": return None
    return city

def phone_key(s): return re.sub(r"\D", "", s or "")[-10:]
def existing():
    out = set(); phones = set()
    for db in [ROOT / "data" / "hunter.sqlite3", ROOT / "data" / "opportunity_hunter.sqlite3"]:
        if not db.exists(): continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            for table in tables:
                cols = {r[1] for r in con.execute(f'pragma table_info("{table}")')}
                if "name" in cols:
                    has_phone = "phone" in cols
                    q = f'select name, city, website{", phone" if has_phone else ""} from "{table}"'
                    for row in con.execute(q):
                        name, city, website = row[:3]; phone = row[3] if has_phone else ""
                        out.add((norm(name), norm(city)))
                        if website: out.add(("domain", host(website)))
                        if phone_key(phone): phones.add(phone_key(phone))
            con.close()
        except Exception: pass
    return out, phones

def main():
    now = datetime.now(timezone.utc).isoformat()
    files = sorted(OUT.glob("maps-*.json"))
    seen, seen_phones = existing(); selected=[]; exclusions=[]; keys=set(); source_queries=[]
    initial_names = set()
    initial_path = OUT / "discovery-initial.json"
    if initial_path.exists():
        for old in json.loads(initial_path.read_text()):
            if old.get("name") not in {"Marks Auto Service of Belvidere", "Altamore's Automotive Service"}:
                initial_names.add(norm(old.get("name")))
    for path in files:
        rows = json.loads(path.read_text())
        for r in rows:
            name, address, site = r.get("name",""), r.get("maps_address", ""), r.get("website", "")
            city = town(address); h = host(site)
            reason = None
            if r.get("maps_query") not in source_queries: source_queries.append(r.get("maps_query"))
            if not city: reason = "address missing or outside approved towns"
            elif norm(name) in initial_names: reason = "prior pilot or baseline candidate"
            elif not site or h in SOCIAL: reason = "no official website"
            elif not r.get("maps_phone"): reason = "no public phone"
            elif any(x in name.lower() for x in FRANCHISE): reason = "obvious franchise or regional chain"
            elif (norm(name), norm(city)) in seen: reason = "existing name/city"
            elif ("domain", h) in seen: reason = "existing domain"
            elif phone_key(r.get("maps_phone")) in seen_phones: reason = "existing phone overlap; review"
            else:
                key = r.get("maps_place_id") or h or (norm(name), norm(city))
                if key in keys: reason = "duplicate listing"
                elif len(selected) >= 10: reason = "selection limit"
                else:
                    keys.add(key)
                    selected.append({
                        "name": name, "city": city, "industry": r.get("industry") or r.get("google_category") or "Unknown",
                        "website": site, "discovery_source": r.get("discovery_source") or r.get("maps_url"),
                        "maps_url": r.get("maps_url"), "maps_place_id": r.get("maps_place_id"), "maps_cid": r.get("maps_cid"),
                        "maps_address": address, "maps_phone": r.get("maps_phone"), "google_category": r.get("google_category"),
                        "google_rating": r.get("google_rating"), "google_review_count": r.get("google_review_count"),
                        "maps_checked_at": r.get("maps_checked_at"), "maps_query": r.get("maps_query"),
                        "source_artifact": str(path.relative_to(ROOT)), "pilot_observed_at": now,
                    })
                    # Preserve immutable Maps provenance from the original discover_maps row.
                    for k, v in r.items():
                        if k.startswith("maps_") or k.startswith("google_"):
                            selected[-1][k] = v
            if reason: exclusions.append({"name": name, "address": address, "reason": reason, "source": str(path.relative_to(ROOT))})
    (OUT / "candidates.json").write_text(json.dumps(selected, indent=2, ensure_ascii=False) + "\n")
    provenance = []
    for row in selected:
        raw = row.get("maps_artifact"); absolute = ROOT / raw if raw else None
        actual = hashlib.sha256(absolute.read_bytes()).hexdigest() if absolute and absolute.is_file() else None
        provenance.append({"name": row["name"], "maps_artifact": raw, "artifact_inside_project": bool(absolute and absolute.is_file()),
                           "expected_sha256": row.get("maps_sha256"), "actual_sha256": actual, "hash_matches": bool(actual and actual == row.get("maps_sha256"))})
    summary = {"generated_at": now, "observed_files": [str(p.relative_to(ROOT)) for p in files], "source_queries": source_queries,
               "seen_existing_identity_count": len(seen), "candidate_pool_count": len(selected), "selected_count": len(selected),
               "selection_limit": 10, "exclusions": exclusions, "unresolved": [] if len(selected)==10 else ["Need more bounded source queries to reach ten"],
               "notes": "Maps results are discovery evidence only. Official-site audit and qualification remain unresolved for parent workflow.",
               "provenance": provenance}
    (OUT / "discovery-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"selected": [(x["name"],x["city"]) for x in selected], "count":len(selected), "excluded":len(exclusions)}))
if __name__ == "__main__": main()
