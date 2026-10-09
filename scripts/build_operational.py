#!/usr/bin/env python3
"""Build data/operational.json, the single file the operational-picture page reads.

Inputs (all plain JSON, fetched by the GitHub Action from the source repos):
  population_movement : pop_trends.json, tp_data.json
  rrp_2026            : data.json, indicator_config.json, targets_2026.json
  this repo           : data/manual.json  (hand-edited: RRP funded %, featured links)

  python3 scripts/build_operational.py --sources .sources \
      --manual data/manual.json --out data/operational.json

The script stops with a non-zero exit code if a source is missing or has an
unexpected shape, so a bad upstream file never overwrites the last good output.
The output is rewritten only when its content changed (the "generated" stamp
is ignored in that comparison), which keeps the commit history quiet.

Partner achievements follow the RRP 2026 dashboard (rrp_2026/index.html) rule
for rule: one achievement per row, rolled up per indicator by the indicator's
methodology (Sum / Max Raion / Max Countrywide / Max Countrywide / Max Raion),
compared with the 2026 target; a sector's progress is achieved / target summed
over its indicators that have a target. Keep this in step with that page.
"""
import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# the 37 first-level units the RRP dashboard maps (norm() of their names)
RAION_KEYS = set("""anenii noi|balti|basarabeasca|bender|briceni|cahul|calarasi|cantemir|
causeni|chisinau|cimislia|criuleni|donduseni|drochia|dubasari|edinet|falesti|floresti|
glodeni|hincesti|ialoveni|leova|nisporeni|ocnita|orhei|rezina|riscani|singerei|soldanesti|
soroca|stefan voda|straseni|taraclia|telenesti|transnistrian region|ungheni|uta gagauzia
""".replace("\n", "").split("|"))

# column names in the ActivityInfo extract (lower-case; first match wins),
# the same lists as CONFIG in rrp_2026/index.html
COLS = {
    "partner": ["partner partner", "partner", "organization", "organisation"],
    "sector": ["sector - outcome area sector", "select sectors targeted by this project",
               "sector", "cluster"],
    "scope": ["geographical scope", "scope"],
    "admin1": ["location admin 1 name", "admin 1", "admin1", "raion", "district"],
    "indicator": ["indicators 2026 indicator 2026", "indicator"],
    "until": ["until month"],
    "reported": ["reporting month"],
}
ACH = {
    "total": ["total achievement"],
    "hostTotal": ["host - total achievement", "host total achievement"],
    "female": ["female beneficiaries"],
    "male": ["male beneficiaries"],
    "hostFemale": ["host community female beneficiaries"],
    "hostMale": ["host community male beneficiaries"],
    "refBreakdown": ["refugee boys reached", "refugee girls reached",
                     "refugee men reached", "refugee women reached"],
    "hostBreakdown": ["host community boys reached", "host community girls reahced",
                      "host community girls reached", "host community men reached",
                      "host community women reached"],
}


class SourceError(Exception):
    pass


def norm(s):
    """Same normalisation as norm() in rrp_2026/index.html."""
    s = unicodedata.normalize("NFKD", "" if s is None else str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\x00-\x7F]", " ", s)
    return re.sub(r"\s+", " ", s).lower().strip()


_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


def num_of(v):
    """JS parseFloat(String(v).replace(/[, ]/g, '')), NaN -> 0."""
    m = _NUM.match(str(v).replace(",", "").replace(" ", ""))
    return float(m.group(0)) if m else 0.0


def filled(v):
    return v is not None and str(v).strip() != ""


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise SourceError(f"{path}: {exc}")


# ----------------------------------------------------------------- population

def build_population(pop, tp):
    months = pop.get("months") if isinstance(pop, dict) else None
    if not months:
        raise SourceError("pop_trends.json has no 'months' list")
    need = ("key", "label", "arrivals", "departures", "remaining", "stay_ukraine")
    for m in months:
        miss = [k for k in need if k not in m]
        if miss:
            raise SourceError(f"pop_trends.json month {m.get('key')} lacks {miss}")
    months = sorted(months, key=lambda m: m["key"])
    last = months[-1]
    stay = last["stay_ukraine"]
    for k in ("women", "men", "girls", "boys", "total"):
        if k not in stay:
            raise SourceError(f"pop_trends.json stay_ukraine lacks '{k}'")

    snaps = tp.get("snapshots") if isinstance(tp, dict) else tp
    if not snaps:
        raise SourceError("tp_data.json has no 'snapshots' list")
    for s in snaps:
        if not s.get("date") or not isinstance(s.get("cumulative"), (int, float)) \
                or not isinstance(s.get("trend"), (int, float)):
            raise SourceError(f"tp_data.json has an invalid snapshot: {s}")
    snaps = sorted(snaps, key=lambda s: s["date"])
    tp_last = snaps[-1]

    return {
        "meta": {
            "source": (pop.get("meta") or {}).get("source", ""),
            "methodology_note": (pop.get("meta") or {}).get("methodology_note", ""),
            "updated": pop.get("updated"),
            "first_month": months[0]["key"],
            "last_month": last["key"],
        },
        "months": [{k: m[k] for k in ("key", "label", "arrivals", "departures", "remaining")}
                   for m in months],
        "kpis": {
            "refugees_from_ukraine": {
                "value": stay["total"], "month": last["key"], "label": last["label"],
            },
            "border_crossings": {
                "month": last["key"], "label": last["label"],
                "arrivals": last["arrivals"], "departures": last["departures"],
                "total": last["arrivals"] + last["departures"],
            },
            "tp_beneficiaries": {
                # as-of is the newest snapshot, not the file's 'updated' field
                "value": tp_last["cumulative"], "date": tp_last["date"],
                "new_in_interval": tp_last["trend"] if tp_last["trend"] >= 0 else None,
                "source": "IGM",
            },
        },
        "demographics": {
            "month": last["key"], "label": last["label"], "total": stay["total"],
            **{k: stay[k] for k in ("women", "men", "girls", "boys")},
        },
    }


# --------------------------------------------------------- partner achievements

def pick(row_lc, names):
    for n in names:
        if n in row_lc:
            return row_lc[n]
    return None


def agg_measure(items, method):
    """items: [(value, raion_group_key)]. Mirrors aggMeasure() in the dashboard."""
    if not items:
        return 0.0
    nums = [v for v, _ in items]

    def max_per_raion(lst):
        g = {}
        for v, k in lst:
            g[k] = max(g.get(k, float("-inf")), v)
        return sum(g.values())

    m = norm(method)
    if m == "max countrywide":
        return max(nums)
    if m == "max raion":
        return max_per_raion(items)
    if m == "max countrywide / max raion":
        located = [x for x in items if x[1] != ""]
        unlocated = [x for x in items if x[1] == ""]
        by_raion = max_per_raion(located) if located else 0
        cw = max(v for v, _ in unlocated) if unlocated else 0
        return max(by_raion, cw)
    return sum(nums)


def build_achievements(rows, config_raw, targets_raw):
    if not isinstance(rows, list) or not rows:
        raise SourceError("data.json is empty or not a list")
    config = {}
    for k, e in config_raw.items():
        config[norm(e.get("indicator") or k)] = e
    t_list = targets_raw.get("indicators") if isinstance(targets_raw, dict) else targets_raw
    if not t_list:
        raise SourceError("targets_2026.json has no indicators")
    targets = {norm(e["indicator"]): num_of(e.get("target")) for e in t_list if e.get("indicator")}

    recs = []
    for r in rows:
        lc = {k.lower().strip(): v for k, v in r.items()}
        g = {k: pick(lc, c) for k, c in COLS.items()}
        cols = {grp: [lc[c] for c in cands if c in lc] for grp, cands in ACH.items()}

        def any_f(grp):
            return any(filled(v) for v in cols[grp])

        def sum_c(grp):
            return sum(num_of(v) for v in cols[grp])

        ref_filled = any_f("refBreakdown") or any_f("female") or any_f("male")
        host_filled = (any_f("hostBreakdown") or any_f("hostFemale")
                       or any_f("hostMale") or any_f("hostTotal"))
        ref = (sum_c("refBreakdown") if any_f("refBreakdown")
               else (sum_c("female") + sum_c("male")) if ref_filled else 0)
        host = (sum_c("hostBreakdown") if any_f("hostBreakdown")
                else (sum_c("hostFemale") + sum_c("hostMale"))
                if (any_f("hostFemale") or any_f("hostMale"))
                else sum_c("hostTotal") if any_f("hostTotal") else 0)
        grand = ref + host if (ref_filled or host_filled) else sum_c("total")

        strip = lambda v: "" if v is None else str(v).strip()
        admin1, scope = strip(g["admin1"]), strip(g["scope"])
        # location comes from the activity's Admin 1 when that column exists
        has_adm = any(n in lc for n in COLS["admin1"])
        toks = [t for t in re.split(r"\s*,\s*", admin1 if has_adm else scope) if t]
        raions = []
        for t in toks:
            k = norm(t)
            if "countrywide" in k:
                continue
            if k in RAION_KEYS:
                raions.append(k)
        recs.append({
            "partner": strip(g["partner"]), "sector": strip(g["sector"]),
            "indicator": strip(g["indicator"]), "grand": grand,
            "raions": raions, "group": "|".join(raions),
            "until": strip(g["until"]) or strip(g["reported"]),
        })

    by_ind = {}
    for rec in recs:
        k = norm(rec["indicator"])
        if k:
            by_ind.setdefault(k, []).append(rec)

    indicators = []
    for k, rs in by_ind.items():
        cfg = config.get(k, {})
        method = cfg.get("method") or "Sum"
        grand = agg_measure([(x["grand"], x["group"]) for x in rs], method)
        tgt = targets.get(k)
        indicators.append({
            "sector": cfg.get("sector") or rs[0]["sector"] or "Not specified",
            "grand": grand,
            "target": tgt if tgt and tgt > 0 else None,
            "partners": {x["partner"] for x in rs if x["partner"]},
        })

    sectors = {}
    for ind in indicators:
        s = sectors.setdefault(ind["sector"], {"n": 0, "n_t": 0, "ach": 0.0, "tgt": 0.0,
                                               "partners": set()})
        s["n"] += 1
        s["partners"] |= ind["partners"]
        if ind["target"] is not None:
            s["n_t"] += 1
            s["ach"] += ind["grand"]
            s["tgt"] += ind["target"]

    out_sectors = []
    for name, s in sectors.items():
        out_sectors.append({
            "sector": name, "indicators": s["n"], "indicators_with_target": s["n_t"],
            "partners": len(s["partners"]),
            "progress_pct": round(s["ach"] / s["tgt"] * 100, 4) if s["tgt"] else None,
        })
    out_sectors.sort(key=lambda s: (s["progress_pct"] is None, -(s["progress_pct"] or 0), s["sector"]))

    with_t = [i for i in indicators if i["target"] is not None]
    sum_t = sum(i["target"] for i in with_t)
    sum_a = sum(i["grand"] for i in with_t)
    until = sorted({x["until"] for x in recs if re.match(r"^\d{4}-\d{2}$", x["until"])})
    return {
        "reported_until": until[-1] if until else None,
        "overall_progress_pct": round(sum_a / sum_t * 100, 4) if sum_t else None,
        "indicators_reported": len(indicators),
        "indicators_with_target": len(with_t),
        "partners": len({x["partner"] for x in recs if x["partner"]}),
        "raions_covered": len({r for x in recs for r in x["raions"]}),
        "sectors": out_sectors,
    }


# ----------------------------------------------------------------------- merge

def build_manual(manual):
    funded = (manual or {}).get("rrp_funded") or {}
    pct = funded.get("pct")
    if not isinstance(pct, (int, float)) or isinstance(pct, bool) or not 0 <= pct <= 100:
        raise SourceError("manual.json: rrp_funded.pct must be a number from 0 to 100")
    for key in ("resources", "dashboards"):
        for item in manual.get(key, []):
            if not item.get("title") or not str(item.get("url", "")).startswith("https://"):
                raise SourceError(f"manual.json: every {key} entry needs a title and an https url")
    return {
        "rrp_funded": {k: funded[k] for k in ("pct", "note", "updated") if k in funded},
        "resources": manual.get("resources", []),
        "dashboards": manual.get("dashboards", []),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sources", required=True, help="folder holding the five source JSON files")
    ap.add_argument("--manual", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    src = Path(a.sources)

    try:
        pop = build_population(load_json(src / "pop_trends.json"), load_json(src / "tp_data.json"))
        ach = build_achievements(load_json(src / "data.json"),
                                 load_json(src / "indicator_config.json"),
                                 load_json(src / "targets_2026.json"))
        man = build_manual(load_json(a.manual))
    except SourceError as exc:
        sys.exit(f"build failed, output left untouched: {exc}")

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kpis": {**pop["kpis"], "rrp_funded": man["rrp_funded"]},
        "population_trends": {"meta": pop["meta"], "months": pop["months"]},
        "demographics": pop["demographics"],
        "partner_achievements": ach,
        "resources": man["resources"],
        "dashboards": man["dashboards"],
    }

    path = Path(a.out)
    # operational.js carries the same data as a script, so the page also opens
    # by double-click from disk, where browsers refuse fetch() on file:// URLs
    js_path = path.with_suffix(".js")
    unchanged = False
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            unchanged = ({k: v for k, v in old.items() if k != "generated"} ==
                         {k: v for k, v in out.items() if k != "generated"})
        except ValueError:
            pass
    if unchanged:
        out = old  # keep the old "generated" stamp so nothing is rewritten
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    js_text = "window.OPERATIONAL_DATA = " + json.dumps(out, ensure_ascii=False, indent=1) + ";\n"
    js_changed = not js_path.exists() or js_path.read_text(encoding="utf-8") != js_text
    if js_changed:
        js_path.write_text(js_text, encoding="utf-8")
    if unchanged and not js_changed:
        print("no change, output untouched")
        return
    print(f"wrote {path} and {js_path.name}: {len(out['population_trends']['months'])} months, "
          f"{ach['indicators_reported']} indicators, {len(ach['sectors'])} sectors")


if __name__ == "__main__":
    main()
