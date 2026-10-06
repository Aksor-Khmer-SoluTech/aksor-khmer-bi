"""Same-origin reference data for demoing `options_source` (see
../report_data.py / ../models/reports.py's OptionsSource) -- a filter
parameter's dropdown fetched from a REST API at run-form/run time,
rather than a static list baked into the report's config. A real
integration would point at whatever system actually owns branch codes;
this exists purely so a sample report's `options_source` has a
same-origin, always-up target that doesn't depend on a third-party API
staying reachable.

Also the demo target for a report's `data_source` -- see
`/revenue-comparison` below, which backs the partner-web "Revenue Comparison"
example report (examples/report_templates/revenue-comparison.docx).
"""
from datetime import date

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/v1/examples", tags=["examples"])

# Not real branch data -- Cambodian-city-shaped so a rendered sample
# report reads naturally.
BRANCHES = [
    {"code": "PP01", "name": "Phnom Penh Main"},
    {"code": "PP02", "name": "Phnom Penh — Chamkar Mon"},
    {"code": "SR01", "name": "Siem Reap"},
    {"code": "BTB01", "name": "Battambang"},
    {"code": "SHV01", "name": "Sihanoukville"},
    {"code": "KPC01", "name": "Kampong Cham"},
]


@router.get(
    "/branches",
    summary="Reference branch list -- demo target for a parameter's options_source",
)
def list_branches() -> list[dict]:
    return BRANCHES


# --- /revenue-comparison: a report's data_source, not just an options list ----

_KHMER_DIGITS = str.maketrans("0123456789", "០១២៣៤៥៦៧៨៩")
_KHMER_MONTHS = [
    "មករា", "កុម្ភៈ", "មីនា", "មេសា", "ឧសភា", "មិថុនា",
    "កក្កដា", "សីហា", "កញ្ញា", "តុលា", "វិច្ឆិកា", "ធ្នូ",
]

# Not real taxpayer data -- the same placeholder dataset partner-web's Revenue
# Comparison modal has always generated from (its `sampleData` catalog flag),
# so the portal's run page and the embedded partner-web report agree. Swap the
# report's data_source URL for the real period-comparison API once one exists;
# nothing about the template or the filters changes.
REVENUE_COMPARISON_GROUPS = [
    {
        "no": "01",
        "nameKh": "កសិកម្ម ព្រៃឈើ និងនេសាទ",
        "nameEn": "Agriculture, forestry and fishing",
        "ent1": 126,
        "amount1": 5386456754,
        "ent2": 126,
        "amount2": 8708834562,
        "diffAmount": 3322377808,
        "diffPercent": 61.68,
        "children": [
            {
                "code": "01",
                "nameKh": "ផលិតកម្មដំណាំ និងសត្វចិញ្ចឹម",
                "ent1": 108,
                "amount1": 5328782251,
                "ent2": 112,
                "amount2": 8599012682,
                "diffAmount": 3270230431,
                "diffPercent": 61.37
            },
            {
                "code": "02",
                "nameKh": "រុក្ខកម្ម និងកាប់ឈើ",
                "ent1": 17,
                "amount1": 56653643,
                "ent2": 14,
                "amount2": 109821880,
                "diffAmount": 53168237,
                "diffPercent": 93.85
            }
        ]
    },
    {
        "no": "03",
        "nameKh": "សកម្មភាពហិរញ្ញវត្ថុ និងធានារ៉ាប់រង",
        "nameEn": "Financial and insurance activities",
        "ent1": 213,
        "amount1": 146394851917,
        "ent2": 205,
        "amount2": 117291396422,
        "diffAmount": -29103455495,
        "diffPercent": -19.88,
        "children": [
            {
                "code": "01",
                "nameKh": "សកម្មភាពសេវាកម្មហិរញ្ញវត្ថុ លើកលែងតែធានារ៉ាប់រង",
                "ent1": 172,
                "amount1": 139920912570,
                "ent2": 163,
                "amount2": 110215718897,
                "diffAmount": -29705193673,
                "diffPercent": -21.23
            },
            {
                "code": "02",
                "nameKh": "ការធានារ៉ាប់រង ការធានារ៉ាប់រងបន្ត និងមូលនិធិសោធន៍",
                "ent1": 28,
                "amount1": 6260200198,
                "ent2": 31,
                "amount2": 6870172823,
                "diffAmount": 609972625,
                "diffPercent": 9.74
            }
        ]
    },
    {
        "no": "12",
        "nameKh": "កម្មន្តសាល",
        "nameEn": "Manufacturing",
        "ent1": 2646,
        "amount1": 210002432363,
        "ent2": 3196,
        "amount2": 225303170961,
        "diffAmount": 15300738598,
        "diffPercent": 7.29,
        "children": [
            {
                "code": "01",
                "nameKh": "ផលិតកម្មៃនផលិតផលម្ហូបអាហារ",
                "ent1": 115,
                "amount1": 9634796585,
                "ent2": 120,
                "amount2": 10342938571,
                "diffAmount": 708141986,
                "diffPercent": 7.35
            },
            {
                "code": "15",
                "nameKh": "កម្មន្តសាល លោហធាតុមូលដ្ឋាន",
                "ent1": 57,
                "amount1": 3830734890,
                "ent2": 71,
                "amount2": 15998676506,
                "diffAmount": 12167941616,
                "diffPercent": 317.64
            }
        ]
    },
    {
        "no": "17",
        "nameKh": "អាហារណីបរិណ ជញ្ជូនយានយន្ត",
        "nameEn": "Wholesale and retail trade",
        "ent1": 637,
        "amount1": 135579758894,
        "ent2": 595,
        "amount2": 134455420413,
        "diffAmount": -1124338481,
        "diffPercent": -0.83,
        "children": [
            {
                "code": "01",
                "nameKh": "ការលក់ដុំ លក់រាយ និងការជួសជុលយានយន្ត",
                "ent1": 75,
                "amount1": 34827345189,
                "ent2": 66,
                "amount2": 30499733188,
                "diffAmount": -4327612001,
                "diffPercent": -12.43
            }
        ]
    }
]


def _dmy(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def _khmer_date(day: date) -> str:
    return f"ថ្ងៃទី {day.day} ខែ {_KHMER_MONTHS[day.month - 1]} ឆ្នាំ {day.year}".translate(_KHMER_DIGITS)


@router.get(
    "/revenue-comparison",
    summary="Sample period-over-period revenue data -- demo target for a report's data_source",
)
def revenue_comparison(
    # Query *names* are camelCase (aliased, Python identifiers stay snake_case
    # per this codebase's own convention) to match the real partner period-
    # comparison API this stands in for -- see the module docstring above:
    # swapping the data_source URL for that real API is meant to need no
    # change to the parameter names the report's filters already send.
    period1_from: date = Query(..., alias="period1FromDate", description="Period 1 start"),
    period1_to: date = Query(..., alias="period1ToDate", description="Period 1 end"),
    period2_from: date = Query(..., alias="period2FromDate", description="Period 2 start"),
    period2_to: date = Query(..., alias="period2ToDate", description="Period 2 end"),
    signed_by: str = Query("", max_length=200, description="Name printed under the signature block; blank leaves it empty"),
) -> dict:
    """The render context revenue-comparison.docx expects. Only the period
    labels (and the printed date/signature) follow the query -- the figures
    are the fixed sample set above."""
    for label, start, end in (("Period 1", period1_from, period1_to), ("Period 2", period2_from, period2_to)):
        if end < start:
            raise HTTPException(status_code=400, detail=f"{label} ends before it starts")

    groups = REVENUE_COMPARISON_GROUPS
    ent1 = sum(g["ent1"] for g in groups)
    amount1 = sum(g["amount1"] for g in groups)
    ent2 = sum(g["ent2"] for g in groups)
    amount2 = sum(g["amount2"] for g in groups)
    diff = amount2 - amount1

    return {
        "issuer": {
            "ministry": "ក្រសួងសេដ្ឋកិច្ច និង ហិរញ្ញវត្ថុ",
            "department": "អគ្គនាយកដ្ឋានពន្ធដារ",
            "unit": "នាយកដ្ឋានគ្រប់គ្រងអ្នកជាប់ពន្ធធំ",
        },
        "addressLine": "អគារលេខ ៣៣៣ វិថីពន្ធដារ សង្កាត់ដ្រាយចង្វារ ខណ្ឌដ្រាយចង្វារ រាជធានីភ្នំពេញ ព្រះរាជាណាចក្រកម្ពុជា",
        "period1": {"label": _dmy(period1_from), "sublabel": _dmy(period1_to)},
        "period2": {"label": _dmy(period2_from), "sublabel": _dmy(period2_to)},
        "total": {
            "ent1": ent1,
            "amount1": amount1,
            "ent2": ent2,
            "amount2": amount2,
            "diffAmount": diff,
            "diffPercent": diff / amount1 * 100 if amount1 > 0 else 0,
        },
        "groups": groups,
        "preparedLocation": "រាជធានីភ្នំពេញ",
        "preparedDate": _khmer_date(date.today()),
        "signatureTitle": "ប្រធាននាយកដ្ឋាន",
        "signatureName": signed_by.strip(),
    }
