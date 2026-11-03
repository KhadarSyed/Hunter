"""Where in the US an article comes from: its export's Country, State and Region (a county, as Meltwater writes it:
"New York County") mapped to the amCharts geodata ids (US-NY; county FIPS 36061), for the us_map chart.

us_geo.json is generated from @amcharts/amcharts5-geodata 5.1.6 (usaLow + region/usa/usaCountiesLow), the same
geodata the deck's map draws, so every id found here has a shape there."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

_GEO = json.loads((Path(__file__).parent / "us_geo.json").read_text(encoding="utf-8"))
STATE_NAMES: dict[str, str] = _GEO["states"]                                      # "US-NY" -> "New York"
_STATES = {**{n.lower(): sid for sid, n in STATE_NAMES.items()}, **{sid[3:].lower(): sid for sid in STATE_NAMES}}
_COUNTIES: dict[str, list[tuple[str, str]]] = {}                                  # "new york county" -> [(fips, US-NY)]
COUNTY_NAMES: dict[str, str] = {}                                                 # fips -> "New York County"
for _fips, _name, _st, _type in _GEO["counties"]:
    _full = f"{_name} {_type}".strip()
    _COUNTIES.setdefault(_full.lower(), []).append((_fips, f"US-{_st}"))
    COUNTY_NAMES[_fips] = _full
_US = {"us", "usa", "united states", "united states of america", "u.s.", "u.s.a."}

MIN_LOCATED = 20        # a map of fewer located articles shows noise, not where the coverage comes from
MIN_SHARE = 0.3         # and most of the question's articles must be on it, or it misrepresents the whole
MIN_STATES = 3          # two states are a comparison, not a map


def _key(value) -> str:
    return " ".join(str(value or "").lower().replace(".", " ").split())


def locate(country, state, region) -> tuple[str | None, str | None]:
    """(state id, county FIPS) of one article; None where its export does not say (or names another country)."""
    if _key(country) and _key(country) not in {_key(c) for c in _US}:
        return None, None
    st = _STATES.get(_key(state)) or _STATES.get(_key(region))      # Region is a state in some exports
    found = _COUNTIES.get(_key(region), [])
    if st:
        found = [c for c in found if c[1] == st]
    if len(found) == 1:          # "Washington County" is in 30 states: only a county its state pins down counts
        return found[0][1], found[0][0]
    return st, None


def aggregate(rows) -> dict:
    """Articles per state and per county, and how many of `rows` carry a US location at all."""
    states, counties, county_state = Counter(), Counter(), {}
    for r in rows:
        a = r.article
        st, fips = locate(a.country, a.state, a.region)
        if st:
            states[st] += 1
        if fips:
            counties[fips] += 1
            county_state[fips] = st
    return {"located": sum(states.values()), "total": len(rows), "states": states, "counties": counties,
            "county_state": county_state}


def map_reason(agg: dict) -> str | None:
    """Why a map answers this question (one line), or None when too few articles carry a US location."""
    located, total, n_states = agg["located"], agg["total"], len(agg["states"])
    if located < MIN_LOCATED or not total or located / total < MIN_SHARE or n_states < MIN_STATES:
        return None
    return (f"geography: {located} of {total} articles ({round(100 * located / total)}%) carry a US state or county, "
            f"across {n_states} states")
