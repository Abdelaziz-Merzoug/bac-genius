"""Historical metadata for every BAC year (2008–2026).

``YEAR_META`` is the single source of truth for:
- ``era``            : curriculum / organisational regime the exam belongs to.
- ``completion_pct`` : *estimated* share of the official programme that was
                       actually taught and examined.  These values are derived
                       from ministerial announcements, union reports and press
                       coverage; they will be refined once the OCR corpus is
                       analysed (topics present in the syllabus map but absent
                       from the extracted questions lower this figure).
- ``session_type``   : how many exam sittings took place that year and why.
- ``censored``       : True for early_reform AND covid years — missing topics
                       must NOT be treated as "never examined" by forecasting
                       models (content was cut by threshold / pandemic, not
                       absent from the curriculum).
- ``sealed``         : True for 2026 — held out as the final evaluation set;
                       no phase may use it for training or analysis.
- ``notes``          : human-readable justification for every non-default value.

Era definitions  (four-era model)
----------------------------------
early_reform  2008–2014  Competency-based reform + "عتبة الدروس" threshold system.
                          CENSORED: missing content was cut by the threshold, not
                          absent from the curriculum — forecasting must not treat
                          those gaps as "topic never examined".
stable        2015–2019  Full programme coverage; بن غبريط abolished the threshold.
covid         2020–2022  Pandemic disruption; partial programme; lowered pass mark.
                          CENSORED: same forecasting rule as early_reform.
modern        2023–2026  Full recovery; 100 % coverage; recency-weighted in models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

Era = Literal["early_reform", "stable", "covid", "modern"]

SessionType = Literal[
    "regular",      # one sitting, no incident
    "reexam",       # partial or full re-examination after a leak / incident
    "exceptional",  # presidential/ministerial exceptional sitting
]


@dataclass(frozen=True)
class SessionRecord:
    """Metadata for one exam sitting within a given year."""

    session: int           # 1 = primary sitting, 2 = second sitting
    session_type: SessionType
    note: str = ""


@dataclass(frozen=True)
class YearMeta:
    """All metadata for one BAC year."""

    year: int
    era: Era
    completion_pct: float          # 0–100; estimate, see module docstring
    sessions: List[SessionRecord]  # ordered list of sittings
    censored: bool = False         # forecast models must not treat gaps as absences
    sealed: bool = False           # held-out evaluation set; never use for training
    notes: str = ""


# ---------------------------------------------------------------------------
# Year-by-year registry
# ---------------------------------------------------------------------------

YEAR_META: Dict[int, YearMeta] = {

    # ── Early-reform era (عتبة الدروس) ────────────────────────────────────

    2008: YearMeta(
        year=2008, era="early_reform", completion_pct=77.5,
        sessions=[SessionRecord(1, "regular")],
        censored=True,
        notes=(
            "First cohort under the competency-based reform (أبو بكر بن بوزيد). "
            "New curricula, delayed school adaptation; عتبة الدروس coined officially "
            "for the first time to protect students from untaught content."
        ),
    ),

    2009: YearMeta(
        year=2009, era="early_reform", completion_pct=85.0,
        sessions=[SessionRecord(1, "regular")],
        censored=True,
        notes=(
            "Relative stabilisation vs 2008; union pressure and student habit "
            "locked the threshold system in place as a pedagogical norm."
        ),
    ),

    2010: YearMeta(
        year=2010, era="early_reform", completion_pct=77.5,
        sessions=[SessionRecord(1, "regular")],
        censored=True,
        notes=(
            "Widespread CNAPESTE / UNPEF strikes paralysed schools for several "
            "weeks; early threshold forced to exclude all post-strike content."
        ),
    ),

    2011: YearMeta(
        year=2011, era="early_reform", completion_pct=80.0,
        sessions=[SessionRecord(1, "regular")],
        censored=True,
        notes=(
            "Arab Spring spillover; repeated student sit-ins. Ministry published "
            "detailed lesson-number reference tables per subject for the first time."
        ),
    ),

    2012: YearMeta(
        year=2012, era="early_reform", completion_pct=82.5,
        sessions=[SessionRecord(1, "regular")],
        censored=True,
        notes=(
            "Threshold maintained as fait-accompli following field-commission "
            "reports and to avoid north/south coverage inequality."
        ),
    ),

    2013: YearMeta(
        year=2013, era="early_reform", completion_pct=87.0,
        sessions=[SessionRecord(1, "regular")],
        censored=True,
        notes=(
            "Official ministerial decision capped content at lessons up to "
            "2 May 2013. Experimental sciences coverage ≈ 86 %, mathematics "
            "≈ 85.7 %, arts/philosophy ≈ 89 %."
        ),
    ),

    2014: YearMeta(
        year=2014, era="early_reform", completion_pct=82.5,
        sessions=[SessionRecord(1, "regular")],
        censored=True,
        notes=(
            "Another prolonged union strike; low official threshold set. "
            "Last year of the classical عتبة system by ministerial design."
        ),
    ),

    # ── Stable era ────────────────────────────────────────────────────────

    2015: YearMeta(
        year=2015, era="stable", completion_pct=97.5,
        sessions=[SessionRecord(1, "regular")],
        notes=(
            "Minister Nouria Benghabrit officially abolished the عتبة system; "
            "full-programme coverage restored. No threshold circular issued."
        ),
    ),

    2016: YearMeta(
        year=2016, era="stable", completion_pct=100.0,
        sessions=[
            SessionRecord(1, "regular",
                          "Primary sitting — June 2016; subjects leaked on Facebook "
                          "before exam centres opened."),
            SessionRecord(2, "reexam",
                          "Partial re-examination 19–23 June 2016; 7 subjects for "
                          "experimental-sciences stream only; full programme scope."),
        ],
        notes=(
            "Largest organised leak in Algerian BAC history. Government ordered "
            "partial rerun; perpetrators jailed. Both sittings cover 100 % of "
            "programme (no content was dropped)."
        ),
    ),

    2017: YearMeta(
        year=2017, era="stable", completion_pct=100.0,
        sessions=[
            SessionRecord(1, "regular",
                          "Primary sitting — June 2017; strict 08:30 door-close "
                          "policy excluded thousands of late candidates."),
            SessionRecord(2, "exceptional",
                          "Full exceptional sitting — July 2017 (presidential "
                          "decree); exclusively for candidates excluded for lateness "
                          "or officially-justified absences."),
        ],
        notes=(
            "No leak; crisis was organisational. Second sitting is NOT a rerun "
            "for all students — only the excluded/absent cohort sat it."
        ),
    ),

    2018: YearMeta(
        year=2018, era="stable", completion_pct=100.0,
        sessions=[SessionRecord(1, "regular")],
        notes=(
            "No incident. Internet blackout during exam hours adopted as the "
            "primary anti-leak countermeasure, replacing the re-exam option."
        ),
    ),

    2019: YearMeta(
        year=2019, era="stable", completion_pct=100.0,
        sessions=[SessionRecord(1, "regular")],
        notes=(
            "Hirak protest movement active since February; schools maintained "
            "full-programme delivery; no threshold or disruption recorded."
        ),
    ),

    # ── COVID era ─────────────────────────────────────────────────────────

    2020: YearMeta(
        year=2020, era="covid", completion_pct=65.0,
        sessions=[SessionRecord(1, "regular",
                                "Delayed to September 2020 due to pandemic closure.")],
        censored=True,
        notes=(
            "Schools closed 12 March 2020 (COVID-19). Exam restricted to "
            "semesters 1 and 2 only; semester 3 cancelled entirely. "
            "Completion capped at ~65 %. CENSORED: absent topics must not "
            "be counted as 'never examined' in forecasting models."
        ),
    ),

    2021: YearMeta(
        year=2021, era="covid", completion_pct=72.5,
        sessions=[SessionRecord(1, "regular")],
        censored=True,
        notes=(
            "Split-cohort (تفويج) system; reduced face-to-face hours; "
            "questions restricted to content delivered in-person. Pass mark "
            "lowered to 9.50/20. CENSORED for the same reason as 2020."
        ),
    ),

    2022: YearMeta(
        year=2022, era="covid", completion_pct=77.5,
        sessions=[SessionRecord(1, "regular")],
        censored=True,
        notes=(
            "Continued COVID-era exceptional plans; pass mark still 9.50/20; "
            "exam restricted to in-person content only. CENSORED."
        ),
    ),

    # ── Modern era ────────────────────────────────────────────────────────

    2023: YearMeta(
        year=2023, era="modern", completion_pct=100.0,
        sessions=[SessionRecord(1, "regular")],
        notes=(
            "All exceptional protocols lifted; pass mark restored to 10/20; "
            "full three-semester programme covered through final week."
        ),
    ),

    2024: YearMeta(
        year=2024, era="modern", completion_pct=100.0,
        sessions=[SessionRecord(1, "regular")],
        notes="Full programme; no strikes; complete timetable observed.",
    ),

    2025: YearMeta(
        year=2025, era="modern", completion_pct=100.0,
        sessions=[SessionRecord(1, "regular")],
        notes="Full programme; questions drawn from all three semesters.",
    ),

    2026: YearMeta(
        year=2026, era="modern", completion_pct=100.0,
        sessions=[SessionRecord(1, "regular")],
        sealed=True,
        notes=(
            "SEALED — held-out evaluation set. Exams ran normally in June 2026. "
            "No phase may use 2026 data for training, topic modeling, "
            "forecasting model fitting, or RAG ingestion."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def get_year(year: int) -> YearMeta:
    """Return metadata for *year*; raises KeyError if out of range."""
    return YEAR_META[year]


def years_in_era(era: Era) -> List[int]:
    """Return all years belonging to *era*, sorted ascending."""
    return sorted(y for y, m in YEAR_META.items() if m.era == era)


def training_years() -> List[int]:
    """Years safe to use for model training (not sealed, ordered)."""
    return sorted(y for y, m in YEAR_META.items() if not m.sealed)


def has_two_sessions(year: int) -> bool:
    """True only for years that produced two distinct exam sittings."""
    return len(YEAR_META[year].sessions) == 2
