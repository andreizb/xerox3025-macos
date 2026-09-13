#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify observed raster behavior from actual offline Apple filter outputs."""
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "evidence/2026-09-09/unattended-print"
cases = {path.parent.name: json.loads(path.read_text())
         for path in (OUT / "cases").glob("*/result.json")}
assert len(cases) == 28, f"Expected 28 measured cases, found {len(cases)}"


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def pages(name): return cases[name]["raster"]["pages"]
def groups(name): return [[x["id"] for x in page["labels"]] for page in pages(name)]
def first(name): return pages(name)[0]
def center(label):
    x, y, w, h = label["box"]
    return x+w/2, 1-y-h/2


checks=[]
def check(name, condition, details):
    checks.append({"check": name, "passed": bool(condition), "details": details})
    assert condition, f"FAILED {name}: {details}"


for name, result in cases.items():
    check(f"{name}: complete native filter and raster decode",
          result["exit_code"] == result.get("decoder_exit_code") == result.get("ocr_exit_code") == 0
          and result["filters"] == ["cgpdftoraster"]
          and result["source_sha256"] == sha(ROOT / result["source"])
          and result["ppd_sha256"] == sha(OUT / "queue-readonly.ppd")
          and all(p["dpi"] == [600,600] and p["bits_per_pixel"] == 8
                  and p["dark_pixels_below_128"] > 0 for p in pages(name)),
          {"page_count": result["raster"]["page_count"], "urf_sha256": result["urf_sha256"]})

sequences = {
    "baseline-4": [1,2,3,4], "range-2-3": [2,3], "range-1-and-4": [1,4],
    "odd-pages": [1,3], "even-pages": [2,4], "reverse-order": [4,3,2,1],
    "even-reverse": [4,2], "collated-2-copies": [1,2,3,4,1,2,3,4],
    "uncollated-2-copies": [1,1,2,2,3,3,4,4],
}
for name, expected in sequences.items():
    actual = groups(name)
    check(f"{name}: actual raster page sequence", actual == [[x] for x in expected], actual)

for number in (2,4,6,9,16):
    name=f"nup-{number}"
    expected=[list(range(start,min(start+number,17))) for start in range(1,17,number)]
    actual=[sorted(group) for group in groups(name)]
    check(f"{name}: actual labels on each sheet", actual == expected, actual)


def grid_ids(name, cols, rows):
    slots = {}
    for label in first(name)["labels"]:
        x, y = center(label)
        key = (min(rows-1,int(y*rows)), min(cols-1,int(x*cols)))
        assert key not in slots, f"Duplicate label in grid cell {name} {key}"
        slots[key] = label["id"]
    return [[slots.get((r,c)) for c in range(cols)] for r in range(rows)]


layout_grids={
    "nup-2": (1,2,[[2],[1]]),  # Portrait raster of a naturally landscape imposition.
    "nup-4": (2,2,[[1,2],[3,4]]),
    "nup-6": (2,3,[[3,6],[2,5],[1,4]]),
    "nup-9": (3,3,[[1,2,3],[4,5,6],[7,8,9]]),
    "nup-16": (4,4,[[1,2,3,4],[5,6,7,8],[9,10,11,12],[13,14,15,16]]),
    "nup-4-rltb": (2,2,[[2,1],[4,3]]),
    "nup-4-tblr": (2,2,[[1,3],[2,4]]),
    "nup-4-border": (2,2,[[1,2],[3,4]]),
}
for name,(cols,rows,expected) in layout_grids.items():
    actual=grid_ids(name,cols,rows)
    check(f"{name}: measured page positions", actual==expected,
          {"top_to_bottom_left_to_right":actual,"coordinate_frame":"physical portrait URF raster"})
check("native N-up border adds raster ink while preserving label placement",
      first("nup-4-border")["dark_pixels_below_128"] > first("nup-4")["dark_pixels_below_128"]*1.1,
      {"none":first("nup-4")["dark_pixels_below_128"],
       "single-thick":first("nup-4-border")["dark_pixels_below_128"]})

for name, millimeters in (("a4-portrait",(210,297)),("a5-media-fit",(148,210)),
                          ("custom-100x150mm",(100,150))):
    p=first(name)
    actual=(p["width"]*25.4/600,p["height"]*25.4/600)
    check(f"{name}: media geometry within one 600 dpi pixel",
          all(abs(a-b)<=25.4/600 for a,b in zip(actual,millimeters)),
          {"actual_mm":actual,"requested_mm":millimeters,"pixels":[p["width"],p["height"]]})

portrait=first("a4-portrait")
for name in ("a4-landscape","a4-reverse-landscape"):
    p=first(name); box=p["labels"][0]["box"]
    check(f"{name}: label rotated and unscaled oversized artwork clipped",
          box[3]>box[2]*2 and p["dark_bounds_inclusive"][0]==0
          and p["dark_bounds_inclusive"][2]==p["width"]-1,
          {"label_box":box,"dark_bounds":p["dark_bounds_inclusive"],
           "interpretation":"Content rotation works. Unscaled portrait artwork exceeds the rotated sheet; this is not a print-dialog fit test."})
front=center(portrait["labels"][0]); back=center(first("a4-reverse-portrait")["labels"][0])
check("reverse portrait: label moves to the opposite half of the raster",
      abs(front[0]+back[0]-1)<.02 and abs(front[1]+back[1]-1)<.02,
      {"portrait_label_center":front,"reverse_label_center":back})
check("landscape plus automatic fit chooses the same best-fit portrait artwork",
      first("a4-landscape-fit")["pixel_sha256"]==portrait["pixel_sha256"],
      {"interpretation":"Observed automatic best fit; not evidence that a forced landscape-with-fit UI choice was tested."})
no_fit=first("wide-none"); fit=first("wide-fit")
check("wide document: fitting removes actual edge clipping",
      no_fit["dark_bounds_inclusive"][2]==no_fit["width"]-1 and
      fit["dark_bounds_inclusive"][0]>0 and fit["dark_bounds_inclusive"][1]>0 and
      fit["dark_bounds_inclusive"][2]<fit["width"]-1 and
      fit["dark_bounds_inclusive"][3]<fit["height"]-1,
      {"unscaled_dark_bounds":no_fit["dark_bounds_inclusive"],"fitted_dark_bounds":fit["dark_bounds_inclusive"],
       "fit_rotates_document":True})
check("PDF CLI scaling=50 does not exercise native scale control",
      first("a4-scale-50")["pixel_sha256"]==portrait["pixel_sha256"],
      {"result":"same pixels as scaling=100; native app transformation still needs separate acceptance"})
check("PDF CLI print-scaling=fill does not exercise Preview Fill Entire Paper",
      first("wide-fill")["pixel_sha256"]==no_fit["pixel_sha256"],
      {"result":"same pixels as unscaled; native app transformation still needs separate acceptance"})

outcomes=[]
for name in cases:
    outcome="behavior_measured_offline"
    if name in ("a4-scale-50","wide-fill"): outcome="native_control_not_exercised_by_cli_alias"
    if name=="a4-landscape-fit": outcome="automatic_best_fit_observed_not_forced_orientation_acceptance"
    outcomes.append({"case":name,"outcome":outcome,"page_count":cases[name]["raster"]["page_count"],
                     "label_groups":groups(name),"evidence":f"cases/{name}/result.json"})
summary={"scope":"OFFLINE host rendering on this Mac. No printer, scan, or print-dialog acceptance is implied.",
         "cases_measured":len(cases),"raster_pages_fully_decoded":sum(x["raster"]["page_count"] for x in cases.values()),
         "assertions_passed":len(checks),"physical_prints":0,"cups_jobs_submitted":0,
         "runtime_or_queue_changes":0,"cases":outcomes,"checks":checks,
         "still_requires_native_ui":["Preview percentage scale", "Preview Fill Entire Paper", "forced orientation combined with fit"],
         "still_requires_owner":["paper sequence and actual copy count", "manual-duplex refeed direction and odd-page handling",
                                 "physical printable margins and registration", "A5/custom media feeding", "toner consumption and density/edge-enhancement effect"]}
(OUT / "acceptance.json").write_text(json.dumps(summary,indent=2)+"\n")
print(json.dumps({k:summary[k] for k in ("cases_measured","raster_pages_fully_decoded","assertions_passed","physical_prints","cups_jobs_submitted")}))
