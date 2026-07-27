#!/usr/bin/env python3
"""NVIDIA 공개 S3에서 선별 에셋을 /home/gty/urban_sim/assets_nvidia/ 로 내려받기 (재개 가능)"""
import os, sys, urllib.request, urllib.parse, xml.etree.ElementTree as ET

B = "https://omniverse-content-production.s3-us-west-2.amazonaws.com"
ROOT = "Assets/Isaac/5.0/"
DEST = "/home/gty/urban_sim/assets_nvidia/"
NS = {'s': 'http://s3.amazonaws.com/doc/2006-03-01/'}

SPECIES = ["Japanese_Cherry", "Black_Oak", "Honey_Locust", "American_Beech", "Japanese_Maple", "Gray_Birch"]
JOBS = [  # (prefix under ROOT, substring filters or None=all)
    ("NVIDIA/dsready_content/nv_content/common_assets/traffic_lights/", None),
    ("NVIDIA/dsready_content/nv_content/korea/country_assets/", None),
    ("NVIDIA/dsready_content/nv_content/common_assets/props_traffic/", ["bollard_01/", "bollard_low/", "bollard_high/", "barricade_01/", "barricade_02/", "barrel_01/"]),
    ("NVIDIA/dsready_content/nv_content/common_assets/props_poles/", ["gen_street_lamp_01/", "lamppost02/"]),
    ("NVIDIA/Assets/Vegetation/Trees/", SPECIES + ["materials/"]),
]

def list_keys(prefix):
    tok = None
    while True:
        u = f"{B}/?list-type=2&prefix={urllib.parse.quote(ROOT + prefix)}"
        if tok: u += f"&continuation-token={urllib.parse.quote(tok)}"
        root = ET.fromstring(urllib.request.urlopen(u, timeout=60).read())
        for c in root.findall('s:Contents', NS):
            yield c.find('s:Key', NS).text, int(c.find('s:Size', NS).text)
        t = root.find('s:NextContinuationToken', NS)
        if t is None: return
        tok = t.text

done = tot = skip = 0
for prefix, filters in JOBS:
    for key, size in list_keys(prefix):
        rel = key[len(ROOT):]
        if "/.thumbs/" in rel: continue
        if filters and not any(f in rel for f in filters): continue
        out = DEST + rel
        if os.path.exists(out) and os.path.getsize(out) == size:
            skip += 1; continue
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            urllib.request.urlretrieve(f"{B}/{urllib.parse.quote(key)}", out)
            done += 1; tot += size
            if done % 25 == 0: print(f"[pull] {done} files {tot/1e6:.0f}MB", flush=True)
        except Exception as e:
            print(f"[pull] FAIL {rel}: {e}", flush=True)
print(f"[pull] COMPLETE new={done} skip={skip} {tot/1e6:.0f}MB", flush=True)
