"""Download a reproducible road-only extract. No crash or imagery data is requested."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
ROAD_URL = "https://gis.massdot.state.ma.us/arcgis/rest/services/Roads/RoadInventoryYearEndFiles/FeatureServer/8"
TOWN_URL = "https://services8.arcgis.com/o4UVke7qqC8oNJ7j/ArcGIS/rest/services/Massachusetts_Towns_General_Coast/FeatureServer/0"
DICTIONARY_URL = "https://www.mass.gov/doc/road-inventory-data-dictionary/download"
TOWNS = ["Boston", "Brookline", "Cambridge", "Dedham", "Everett", "Milton", "Needham",
         "Newton", "Quincy", "Revere", "Somerville", "Watertown", "Winthrop"]
FIELDS = ["OBJECTID", "GlobalID", "Rd_Seg_ID", "City", "St_Name", "F_Class", "F_F_Class",
          "Facility", "Mile_Count", "Length", "Shape__Length", "Num_Lanes", "Opp_Lanes",
          "Surface_Wd", "Speed_Lim", "Speed", "Op_Dir_SL", "AADT", "AADT_Year", "AADT_Deriv",
          "Lt_Sidewlk", "Rt_Sidewlk", "Operation", "Control", "Jurisdictn"]


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_json(url, params):
    # ArcGIS supports read-only query requests over POST, avoiding long object-ID URLs.
    data = urllib.parse.urlencode(params).encode() if url.endswith("/query") else None
    address = url if data is not None else url + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            request = urllib.request.Request(address, data=data)
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.load(response)
            if "error" in payload:
                raise RuntimeError(payload["error"])
            return payload
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["towns"] != TOWNS or manifest["fields"] != FIELDS:
            raise ValueError("Configuration changed. Preserve this snapshot and use a new data folder.")
        if manifest["status"] == "complete":
            for relative, digest in manifest["sha256"].items():
                assert checksum(RAW / relative) == digest, relative
            print(f"Verified complete cached snapshot: {manifest['downloaded_records']:,} roads.")
            return
        metadata = json.loads((RAW / "road_layer.json").read_text())
    else:
        metadata = get_json(ROAD_URL, {"f": "json"})
        save(RAW / "road_layer.json", metadata)
        available = {field["name"] for field in metadata["fields"]}
        assert set(FIELDS) <= available, sorted(set(FIELDS) - available)
        city_field = next(field for field in metadata["fields"] if field["name"] == "City")
        codes = {item["name"].upper(): item["code"] for item in city_field["domain"]["codedValues"]}
        city_ids = [codes[town.upper()] for town in TOWNS]
        where = "City IN (" + ",".join(map(str, sorted(city_ids))) + ")"
        ids = sorted(get_json(ROAD_URL + "/query", {"f": "json", "where": where,
                                                   "returnIdsOnly": "true"})["objectIds"])
        count = get_json(ROAD_URL + "/query", {"f": "json", "where": where,
                                              "returnCountOnly": "true"})["count"]
        assert count == len(ids) == len(set(ids))
        # Use the same municipal IDs for the boundary reference, without selecting by outcomes.
        towns = get_json(TOWN_URL + "/query", {"f": "json", "where": "TOWN_ID IN (" +
            ",".join(map(str, sorted(city_ids))) + ")", "outFields": "TOWN_ID,TOWN",
            "returnGeometry": "true", "outSR": 26986})
        assert {f["attributes"]["TOWN"].upper() for f in towns["features"]} == {t.upper() for t in TOWNS}
        save(RAW / "municipalities.json", towns)
        manifest = {"status": "partial", "started_at_utc": now(), "road_source": ROAD_URL,
            "road_layer_name": metadata.get("name"), "boundary_source": TOWN_URL,
            "dictionary_source": DICTIONARY_URL, "towns": TOWNS, "city_ids": city_ids,
            "where": where, "fields": FIELDS, "requested_ids": ids, "server_count_at_start": count,
            "inventory_year": 2022, "out_crs": "EPSG:26986", "batch_size": 500,
            "scope_source": "geospatial-eda/01_raw_data_preprocessing.ipynb, commit a48cc6b96157cd000e4e5ef1f02c28dd9f466366",
            "note": "Fresh public-service extract, not Molly's original October snapshot. Requests are not an atomic database snapshot."}
        save(manifest_path, manifest)

    ids, size = manifest["requested_ids"], manifest["batch_size"]

    def batch(start):
        wanted = ids[start:start + size]
        path = RAW / "batches" / f"roads_{start:06d}.json"
        if path.exists():
            result = json.loads(path.read_text())
        else:
            result = get_json(ROAD_URL + "/query", {"f": "json", "objectIds": ",".join(map(str, wanted)),
                "outFields": ",".join(FIELDS), "returnGeometry": "true", "outSR": 26986})
            observed = [feature["attributes"]["OBJECTID"] for feature in result.get("features", [])]
            assert sorted(observed) == wanted and not result.get("exceededTransferLimit"), start
            save(path, result)
        observed = [feature["attributes"]["OBJECTID"] for feature in result["features"]]
        assert sorted(observed) == wanted and len(set(observed)) == len(observed), start
        assert result["spatialReference"].get("latestWkid", result["spatialReference"]["wkid"]) == 26986
        return len(observed)

    downloaded = 0
    with ThreadPoolExecutor(max_workers=3) as workers:
        for index, total in enumerate(workers.map(batch, range(0, len(ids), size))):
            downloaded += total
            if index % 10 == 0 or downloaded == len(ids):
                print(f"Verified {downloaded:,}/{len(ids):,} road records", flush=True)
    assert downloaded == len(ids)
    dictionary = RAW / "road_inventory_dictionary.pdf"
    if not dictionary.exists():
        with urllib.request.urlopen(DICTIONARY_URL, timeout=60) as response:
            body = response.read()
        assert body.startswith(b"%PDF"), "Dictionary endpoint did not return a PDF"
        dictionary.write_bytes(body)
    paths = sorted((RAW / "batches").glob("*.json")) + [RAW / "road_layer.json", RAW / "municipalities.json", dictionary]
    manifest.update(status="complete", completed_at_utc=now(), downloaded_records=downloaded,
                    sha256={str(path.relative_to(RAW)): checksum(path) for path in paths})
    save(manifest_path, manifest)
    print("Complete. Raw source fields, geometries, dictionary and checksums are preserved.", flush=True)


if __name__ == "__main__":
    main()
