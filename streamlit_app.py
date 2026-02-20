import json
from io import BytesIO
from datetime import datetime
import pandas as pd
import streamlit as st

# ============================================================
# IEC 62915:2023 Retesting Planner (Decision Support)
# Implements modification-driven retest logic per IEC TS 62915:2023 (Edition 2.0, 2023-09)
# References:
#  - Clause 4.1: General (baseline, Gate-1/Gate-2, stabilization, combined flow)
#  - Clauses 4.2/4.3: WBT vs MLI modification families & required tests
#  - Annex A: Combined test flow IEC 61215 & IEC 61730 (sequences & identifiers)
# NOTE: This tool supports decision-making; final programs must be validated by qualified engineers.
# ============================================================

st.set_page_config(page_title="IEC 62915:2023 – Retesting Planner", layout="wide")

# -----------------------
# Data dictionaries
# -----------------------

TESTS_61215 = {
    "MQT 01": "Visual inspection",
    "MQT 03": "Insulation test (61215 context)",
    "MQT 04": "Measurement of temperature coefficients",
    "MQT 06.1": "Performance at STC",
    "MQT 07": "Performance at low irradiance",
    "MQT 09": "Hot-spot endurance",
    "MQT 10": "UV preconditioning",
    "MQT 11-50": "Thermal cycling (50 cycles)",
    "MQT 11-200": "Thermal cycling (200 cycles)",
    "MQT 12": "Humidity freeze",
    "MQT 13": "Damp heat",
    "MQT 14.1": "Robustness of terminations – retention of junction box on mounting surface",
    "MQT 14.2": "Robustness of terminations – cord anchorage",
    "MQT 15": "Wet leakage current test (61215 context)",
    "MQT 16": "Static mechanical load",
    "MQT 17": "Hail test",
    "MQT 18": "Bypass diode thermal test",
    "MQT 18.1": "Bypass diode thermal test (bifacial context)",
    "MQT 19": "Stabilization",
    "MQT 20": "Cyclic (dynamic) mechanical load",
    "MQT 21": "Potential-induced degradation (PID)",
    "MQT 22": "Bending test (flexible module)"
}

TESTS_61730 = {
    "MST 01": "Visual inspection (61730 context)",
    "MST 03": "Insulation test (61730 context)",
    "MST 04": "Insulation thickness test",
    "MST 05": "Durability of markings",
    "MST 06": "Sharp edges",
    "MST 07": "Bypass diode functionality",
    "MST 11": "Accessibility test",
    "MST 12": "Cut susceptibility test",
    "MST 13": "Continuity of equipotential bonding",
    "MST 14": "Impulse voltage test",
    "MST 16": "Wet leakage current test (61730 context)",
    "MST 17": "Ground continuity test",
    "MST 22": "Hot-spot endurance",
    "MST 24": "Ignitability",
    "MST 25": "Bypass diode thermal (61730 numbering in some editions)",
    "MST 26": "Reverse current overload",
    "MST 32": "Module breakage",
    "MST 33": "Screw connections test",
    "MST 34": "Static mechanical load",
    "MST 35": "Peel test (cemented joints)",
    "MST 36": "Lap shear strength (cemented joints)",
    "MST 37": "Materials creep",
    "MST 42": "Robustness of terminations (61730)",
    "MST 51-50": "Thermal cycling (50 cycles)",
    "MST 51-200": "Thermal cycling (200 cycles)",
    "MST 52": "Humidity freeze",
    "MST 53": "Damp heat",
    "MST 54": "UV test",
    "MST 57": "Insulation coordination evaluation (61730-1 reference)",
    # Sequence B/B1 are handled as 'sequence flags'
}

SEQUENCE_FLAGS = {
    "SEQ_B": "61730 Sequence B (apply when non-glass polymeric outer surface or specific adhesive/label cases)",
    "SEQ_B1": "61730 Sequence B1 (pollution degree 1 variants)"
}

# -----------------------
# Utilities
# -----------------------

def add_test(plan, standard, code, reason, clause):
    """Add a test with dedup on (standard, code). Accumulate reasons and clauses."""
    key = (standard, code)
    name = (TESTS_61215 if standard == "IEC 61215" else TESTS_61730).get(code, code)
    if key not in plan:
        plan[key] = {
            "Standard": standard,
            "Test ID": code,
            "Test name": name,
            "Reasons": set([reason]) if reason else set(),
            "Clauses": set([clause]) if clause else set(),
            "Notes": set()
        }
    else:
        if reason:
            plan[key]["Reasons"].add(reason)
        if clause:
            plan[key]["Clauses"].add(clause)

def add_note(plan, note):
    """Store general notes (non-test items; we’ll render in a separate section)."""
    plan.setdefault(("NOTES", "NOTES"), {"NotesOnly": []})
    plan[("NOTES", "NOTES")]["NotesOnly"].append(note)

def add_sequence_flag(seq_set, flag, clause):
    seq_set.add((flag, clause))

def baseline_checks(include_61215, include_61730, plan):
    # Clause 4.1: baseline checks and stabilization
    if include_61215:
        for t in ["MQT 01", "MQT 03", "MQT 06.1", "MQT 15", "MQT 19"]:
            add_test(plan, "IEC 61215", t, "Baseline initial/final measurements per 4.1", "4.1")
    if include_61730:
        for t in ["MST 01", "MST 03", "MST 16", "MST 17"]:
            add_test(plan, "IEC 61730", t, "Baseline checks per 4.1 (61730 program)", "4.1")

# -----------------------
# Rule Engine – Selected coverage from 4.2 (WBT) and 4.3 (MLI)
# The rules below are paraphrased & encoded; see comments for mapping to the TS.
# -----------------------

def rules_frontsheet(params, tech, include_61215, include_61730, seq_flags, plan):
    """
    4.2.1 (WBT) and 4.3.1 (MLI): frontsheet
    Inputs:
      - material_type: 'glass' or 'polymeric'
      - thickness_change_pct
      - surface_treatment_changed (bool)
      - ar_lambda_c_uv_change: '>= previous' / '< previous' / 'unknown' (for glass UV cutoff comparison)
      - strengthening_change (glass) (bool)
      - glass_to_poly_or_vice_versa (bool)
    """
    p = params
    glass = p.get("material_type") == "glass"
    non_glass = not glass
    thickness_change = p.get("thickness_change_pct") or 0.0
    surface_change = p.get("surface_treatment_changed", False)
    ar_cmp = p.get("ar_lambda_c_uv_change", "unknown")  # >= previous or <
    strengthen_change = p.get("strengthening_change", False)
    model_designation_change = p.get("model_designation_change", False)  # polymeric series change per 62788-2-1
    glass_to_from_nonglass = p.get("glass_to_poly_or_vice_versa", False)

    if glass_to_from_nonglass:
        # Full qualification is required by TS (out of scope for “retest” only)
        add_note(plan, "Frontsheet change between glass and non-glass suggests full qualification (TS 4.2.1/4.3.1).")
        # We still propose a conservative retest set; engineer to decide final path.

    # IEC 61215 set
    if include_61215:
        # Hot-spot (if glass: material/strength change or thickness reduced; if polymeric: general)
        if glass and (strengthen_change or thickness_change < 0):
            add_test(plan, "IEC 61215", "MQT 09", "Frontsheet: glass strength/thickness change", "4.2.1/4.3.1")
        if non_glass and (model_designation_change or thickness_change < 0):
            add_test(plan, "IEC 61215", "MQT 09", "Frontsheet non-glass model/thickness change", "4.2.1/4.3.1")

        # UV+DynML+TC50+HF sequence; may omit if glass with λcUV >= previous
        if not (glass and ar_cmp == ">= previous"):
            add_test(plan, "IEC 61215", "MQT 10", "UV preconditioning for frontsheet change", "4.2.1/4.3.1")
            add_test(plan, "IEC 61215", "MQT 20", "Cyclic (dynamic) mechanical load", "4.2.1/4.3.1")
            add_test(plan, "IEC 61215", "MQT 11-50", "Thermal cycling 50 cycles", "4.2.1/4.3.1")
            add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.1/4.3.1")
            # J-Box retention 14.1 if J-Box is on the frontsheet (user toggle below)
            if p.get("jb_on_frontsheet", False):
                add_test(plan, "IEC 61215", "MQT 14.1", "Retention of J-box on frontsheet", "4.2.1/4.3.1")

        # Damp heat if non-glass or surface treatment changed
        if non_glass or surface_change:
            add_test(plan, "IEC 61215", "MQT 13", "Damp heat for frontsheet change", "4.2.1/4.3.1")

        # Bending if module is “flexible” (user flag)
        if p.get("flexible_module", False) and non_glass:
            add_test(plan, "IEC 61215", "MQT 22", "Bending test for flexible non-glass", "4.2.1/4.3.1")

        # Static ML (can omit for only outside surface treatment)
        if not (surface_change and p.get("outside_surface_only", False)):
            add_test(plan, "IEC 61215", "MQT 16", "Static mechanical load (frontsheet)", "4.2.1/4.3.1")

        # Hail test (can omit for only surface treatment)
        if not (surface_change and p.get("outside_surface_only", False)):
            add_test(plan, "IEC 61215", "MQT 17", "Hail test (frontsheet change)", "4.2.1/4.3.1")

    # IEC 61730 set
    if include_61730:
        # UV + TC50 + HF + Robustness of terminations (MST 42); may omit if glass with λcUV >= previous
        if not (glass and ar_cmp == ">= previous"):
            add_test(plan, "IEC 61730", "MST 54", "UV test for frontsheet change", "4.2.1/4.3.1")
            add_test(plan, "IEC 61730", "MST 51-50", "Thermal cycling 50 cycles", "4.2.1/4.3.1")
            add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.2.1/4.3.1")
            if p.get("jb_on_frontsheet", False):
                add_test(plan, "IEC 61730", "MST 42", "Robustness of terminations (frontsheet J-box)", "4.2.1/4.3.1")

        # Damp heat if non-glass or surface treatment changed
        if non_glass or surface_change:
            add_test(plan, "IEC 61730", "MST 53", "Damp heat for frontsheet change", "4.2.1/4.3.1")

        # Static mechanical load (not for outside surface-only change)
        if not (surface_change and p.get("outside_surface_only", False)):
            add_test(plan, "IEC 61730", "MST 34", "Static mechanical load (frontsheet)", "4.2.1/4.3.1")

        if non_glass:
            add_test(plan, "IEC 61730", "MST 04", "Insulation thickness test (non-glass)", "4.2.1/4.3.1")
            add_test(plan, "IEC 61730", "MST 12", "Cut susceptibility (non-glass)", "4.2.1/4.3.1")
            # Impulse voltage/ignitability if changed or reduced
            if model_designation_change or thickness_change < 0:
                add_test(plan, "IEC 61730", "MST 14", "Impulse voltage test (non-glass changed/reduced)", "4.2.1/4.3.1")
            add_test(plan, "IEC 61730", "MST 24", "Ignitability (non-glass)", "4.2.1/4.3.1")
            add_sequence_flag(seq_flags, "SEQ_B", "4.2.1/4.3.1")

        # Module breakage for glass (except only surface treatment that doesn't impair strength)
        if glass and not (surface_change and p.get("outside_surface_only", False)):
            add_test(plan, "IEC 61730", "MST 32", "Module breakage (glass)", "4.2.1/4.3.1")

        # Cemented joint cases
        if p.get("cemented_joint", False):
            add_test(plan, "IEC 61730", "MST 35", "Peel test (cemented joint)", "4.2.1/4.3.1")
            add_test(plan, "IEC 61730", "MST 36", "Lap shear (cemented joint)", "4.2.1/4.3.1")


def rules_encapsulation(params, tech, include_61215, include_61730, seq_flags, plan):
    """
    4.2.2 / 4.3.2 encapsulation system
    Inputs: different_material, additives_change_same_material, thickness_change_pct, volume_resistivity_drop_order (int), flexible_module
    """
    p = params
    diff_mat = p.get("different_material", False)
    add_change = p.get("additives_change_same_material", False)
    thickness_change = p.get("thickness_change_pct") or 0.0
    flexible = p.get("flexible_module", False)
    rho_drop_order = p.get("volume_resistivity_drop_order", 0)

    if include_61215:
        add_test(plan, "IEC 61215", "MQT 09", "Encapsulation change", "4.2.2/4.3.2")
        # UV + DynML + TC50 + HF (omit MQT20 only if additives change but same material)
        add_test(plan, "IEC 61215", "MQT 10", "UV preconditioning", "4.2.2/4.3.2")
        if not add_change:
            add_test(plan, "IEC 61215", "MQT 20", "Cyclic (dynamic) mechanical load", "4.2.2/4.3.2")
        add_test(plan, "IEC 61215", "MQT 11-50", "Thermal cycling 50", "4.2.2/4.3.2")
        add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.2/4.3.2")

        if thickness_change < -20.0:
            add_test(plan, "IEC 61215", "MQT 11-200", "Thermal cycling 200 (thickness reduction >20%)", "4.2.2/4.3.2")

        add_test(plan, "IEC 61215", "MQT 13", "Damp heat", "4.2.2/4.3.2")

        if p.get("frontsheet_polymeric", False):
            if diff_mat or not add_change:
                add_test(plan, "IEC 61215", "MQT 17", "Hail test (polymeric frontsheet)", "4.2.2")

        if rho_drop_order and rho_drop_order >= 1:
            add_test(plan, "IEC 61215", "MQT 21", "PID (volume resistivity decrease ≥1 order)", "4.2.2")

        if flexible:
            add_test(plan, "IEC 61215", "MQT 22", "Bending test (flexible)", "4.2.2")

    if include_61730:
        add_test(plan, "IEC 61730", "MST 22", "Hot-spot endurance", "4.2.2/4.3.2")
        add_test(plan, "IEC 61730", "MST 54", "UV", "4.2.2/4.3.2")
        add_test(plan, "IEC 61730", "MST 51-50", "Thermal cycling 50", "4.2.2/4.3.2")
        add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.2.2/4.3.2")
        add_test(plan, "IEC 61730", "MST 53", "Damp heat", "4.2.2/4.3.2")

        if thickness_change < -20.0:
            add_test(plan, "IEC 61730", "MST 51-200", "Thermal cycling 200 (thickness reduction >20%)", "4.2.2/4.3.2")

        if p.get("front_or_back_polymeric", True):
            add_test(plan, "IEC 61730", "MST 12", "Cut susceptibility (polymeric outer)", "4.2.2/4.3.2")

        if diff_mat or (thickness_change < 0):
            add_test(plan, "IEC 61730", "MST 14", "Impulse voltage (reduced thickness/different material)", "4.2.2/4.3.2")

        if p.get("material_changed_composition", False):
            add_test(plan, "IEC 61730", "MST 32", "Module breakage (material composition change)", "4.2.2")

        if p.get("cemented_joint", False):
            add_test(plan, "IEC 61730", "MST 35", "Peel test (cemented joint)", "4.2.2")
            add_test(plan, "IEC 61730", "MST 36", "Lap shear (cemented joint)", "4.2.2")

        add_test(plan, "IEC 61730", "MST 37", "Materials creep (as applicable)", "4.2.2")

        if diff_mat or (thickness_change < 0):
            add_sequence_flag(seq_flags, "SEQ_B", "4.2.2")
        if p.get("pollution_degree_1", False):
            add_sequence_flag(seq_flags, "SEQ_B1", "4.2.2")


def rules_cell_technology_wbt(params, include_61215, include_61730, plan):
    """
    4.2.3 WBT: cell technology changes
    Inputs: metallization_change, bonded_area_reduction_pct, busbar_increase, ar_change, tech_change,
            crystallization_change, manufacturer_change (not same QMS), cell_thickness_reduction_pct,
            cell_size_change_pct, moved_to_half_cell
    """
    p = params
    if include_61215:
        add_test(plan, "IEC 61215", "MQT 20", "Dyn mech load (cell tech change)", "4.2.3")
        add_test(plan, "IEC 61215", "MQT 11-50", "Thermal cycling 50", "4.2.3")
        add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.3")
        # PID only for tech change / AR / crystallization / manufacturer
        if any([p.get("tech_change"), p.get("ar_change"), p.get("crystallization_change"), p.get("manufacturer_change")]):
            add_test(plan, "IEC 61215", "MQT 21", "PID (cell technology/AR/crystallization/manufacturer change)", "4.2.3")
        add_test(plan, "IEC 61215", "MQT 09", "Hot-spot endurance (cell tech change)", "4.2.3")
        add_test(plan, "IEC 61215", "MQT 11-200", "Thermal cycling 200", "4.2.3")
        # Damp heat may be omitted for crystallization or identical outer surface chemistry
        add_test(plan, "IEC 61215", "MQT 13", "Damp heat (cell tech change)", "4.2.3")
        # Static ML if cell thickness reduced or crystallization change
        if p.get("cell_thickness_reduction_pct", 0) < 0 or p.get("crystallization_change"):
            add_test(plan, "IEC 61215", "MQT 16", "Static mechanical load (thickness/crystallization)", "4.2.3")
        # Hail if reduction of cell thickness
        if p.get("cell_thickness_reduction_pct", 0) < 0:
            add_test(plan, "IEC 61215", "MQT 17", "Hail (reduced cell thickness)", "4.2.3")

    if include_61730:
        add_test(plan, "IEC 61730", "MST 22", "Hot-spot endurance (cell tech)", "4.2.3")
        add_test(plan, "IEC 61730", "MST 51-200", "Thermal cycling 200", "4.2.3")
        # Damp heat may be omitted for crystallization or identical outer chemistry; include conservatively
        add_test(plan, "IEC 61730", "MST 53", "Damp heat (cell tech)", "4.2.3")
        if p.get("cell_thickness_reduction_pct", 0) < 0 or p.get("crystallization_change"):
            add_test(plan, "IEC 61730", "MST 34", "Static mechanical load (thickness/crystallization)", "4.2.3")
        # Reverse current overload (omit for crystallization if per TS; include conditionally)
        if not p.get("crystallization_change", False):
            add_test(plan, "IEC 61730", "MST 26", "Reverse current overload (cell tech)", "4.2.3")


def rules_interconnect_wbt(params, include_61215, include_61730, plan):
    """
    4.2.4 WBT: cell & string interconnect changes
    Inputs: different_material, strength_changes, cross_section_change_pct, bonding_tech_change,
            num_bonds_change, length_change_pct, solder_flux_change, insulation_tape_change
    """
    p = params
    if include_61215:
        add_test(plan, "IEC 61215", "MQT 09", "Hot-spot (bond/IC material/adhesive/flux change)", "4.2.4")
        add_test(plan, "IEC 61215", "MQT 11-200", "Thermal cycling 200", "4.2.4")
        if p.get("different_material") or p.get("solder_flux_change"):
            add_test(plan, "IEC 61215", "MQT 13", "Damp heat (material/flux change)", "4.2.4")
    if include_61730:
        add_test(plan, "IEC 61730", "MST 22", "Hot-spot (bond/IC material/adhesive/flux change)", "4.2.4")
        add_test(plan, "IEC 61730", "MST 51-200", "Thermal cycling 200", "4.2.4")
        if p.get("different_material") or p.get("solder_flux_change"):
            add_test(plan, "IEC 61730", "MST 53", "Damp heat (material/flux change)", "4.2.4")
        add_test(plan, "IEC 61730", "MST 26", "Reverse current overload", "4.2.4")


def rules_backsheet(params, tech, include_61215, include_61730, seq_flags, plan):
    """
    4.2.5 / 4.3.9 backsheet
    Inputs: material_type ('glass'/'polymeric'), thickness_change_pct, surface_treatment_changed, strengthening_change (glass),
            outside_surface_only, jb_on_backsheet, rigidity_depends_on_backsheet, mounting_depends_on_backsheet,
            polymeric_thickness_increase_gt20 (bool)
    """
    p = params
    glass = p.get("material_type") == "glass"
    non_glass = not glass
    thickness_change = p.get("thickness_change_pct") or 0.0
    surface_change = p.get("surface_treatment_changed", False)
    outside_only = p.get("outside_surface_only", False)

    if include_61215:
        # UV + DynML + TC50 + HF + J-box retention (if mounted on backsheet); may omit for glass with λcUV >= previous
        add_test(plan, "IEC 61215", "MQT 10", "UV preconditioning", "4.2.5/4.3.9")
        add_test(plan, "IEC 61215", "MQT 20", "Cyclic (dynamic) mechanical load", "4.2.5/4.3.9")
        add_test(plan, "IEC 61215", "MQT 11-50", "Thermal cycling 50", "4.2.5/4.3.9")
        add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.5/4.3.9")
        if p.get("jb_on_backsheet", False):
            add_test(plan, "IEC 61215", "MQT 14.1", "Retention of J-box on mounting surface", "4.2.5/4.3.9")

        # Damp heat if non-glass or surface treatment changed
        if non_glass or surface_change:
            add_test(plan, "IEC 61215", "MQT 13", "Damp heat (backsheet)", "4.2.5/4.3.9")

        # Bending if flexible & non-glass
        if p.get("flexible_module", False) and non_glass:
            add_test(plan, "IEC 61215", "MQT 22", "Bending test (flexible)", "4.2.5/4.3.9")

        # Static ML if glass or mounting depends on backsheet
        if glass or p.get("mounting_depends_on_backsheet", False):
            add_test(plan, "IEC 61215", "MQT 16", "Static mechanical load (backsheet)", "4.2.5/4.3.9")

        # Hail if rigidity depends on backsheet
        if p.get("rigidity_depends_on_backsheet", False):
            add_test(plan, "IEC 61215", "MQT 17", "Hail (rigidity depends on backsheet)", "4.2.5/4.3.9")

        # Hot-spot for glass (if strength process changes or thickness reduced); non-glass thickness reduce or diff material
        if (glass and (p.get("strengthening_change", False) or thickness_change < 0)) or (non_glass and (thickness_change < 0 or p.get("model_designation_change", False))):
            add_test(plan, "IEC 61215", "MQT 09", "Hot-spot (backsheet change)", "4.2.5/4.3.9")

    if include_61730:
        add_test(plan, "IEC 61730", "MST 54", "UV", "4.2.5/4.3.9")
        add_test(plan, "IEC 61730", "MST 51-50", "Thermal cycling 50", "4.2.5/4.3.9")
        add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.2.5/4.3.9")
        add_test(plan, "IEC 61730", "MST 42", "Robustness of terminations (if applicable)", "4.2.5/4.3.9")
        if non_glass or surface_change:
            add_test(plan, "IEC 61730", "MST 53", "Damp heat", "4.2.5/4.3.9")
        if glass or p.get("mounting_depends_on_backsheet", False):
            add_test(plan, "IEC 61730", "MST 34", "Static mechanical load (backsheet)", "4.2.5/4.3.9")
        if non_glass:
            add_test(plan, "IEC 61730", "MST 04", "Insulation thickness test (non-glass)", "4.2.5/4.3.9")
            add_test(plan, "IEC 61730", "MST 12", "Cut susceptibility (non-glass)", "4.2.5/4.3.9")
            if thickness_change < 0 or p.get("model_designation_change", False):
                add_test(plan, "IEC 61730", "MST 14", "Impulse voltage test (non-glass reduced/changed)", "4.2.5/4.3.9")
            add_test(plan, "IEC 61730", "MST 24", "Ignitability (non-glass)", "4.2.5/4.3.9")
            add_sequence_flag(seq_flags, "SEQ_B", "4.2.5/4.3.9")
        if glass and not outside_only:
            add_test(plan, "IEC 61730", "MST 32", "Module breakage (glass)", "4.2.5/4.3.9")
        if p.get("cemented_joint", False):
            add_test(plan, "IEC 61730", "MST 35", "Peel test (cemented joint)", "4.2.5/4.3.9")
            add_test(plan, "IEC 61730", "MST 36", "Lap shear (cemented joint)", "4.2.5/4.3.9")
        if p.get("pollution_degree_1", False):
            add_sequence_flag(seq_flags, "SEQ_B1", "4.2.5/4.3.9")


def rules_electrical_termination(params, include_61215, include_61730, seq_flags, plan):
    """
    4.2.6 / 4.3.10 electrical termination: JB/cables/connectors; potting; attachment methods; relocation/position; adhesive change
    Inputs: diff_jb, diff_cable_or_conn, num_jb_change, relocate_front_to_back, position_changed,
            potting_change, mech_attachment_change, electrical_attachment_change, jb_prequalified,
            direct_sun_exposure (for UV), adhesive_change, screw_connections_applicable
    """
    p = params

    if include_61215:
        # UV + DynML + TC50 + HF + robustness of terminations (MQT14.1/.2) – with various omission rules
        if not p.get("jb_not_sun_exposed", False) and not p.get("potting_change_only", False):
            add_test(plan, "IEC 61215", "MQT 10", "UV preconditioning (termination)", "4.2.6/4.3.10")
        if not p.get("potting_change_only", False) and not p.get("only_cable_or_connector_change", False):
            add_test(plan, "IEC 61215", "MQT 20", "Dyn. mechanical load (termination)", "4.2.6/4.3.10")
        add_test(plan, "IEC 61215", "MQT 11-50", "Thermal cycling 50", "4.2.6/4.3.10")
        add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.6/4.3.10")
        if not p.get("jb_prequalified", False) and not p.get("only_mech_attachment_or_num_jb", False) and not p.get("relocation_or_position_only", False):
            add_test(plan, "IEC 61215", "MQT 14.2", "Cord anchorage", "4.2.6/4.3.10")
        if not p.get("electrical_attachment_only", False):
            add_test(plan, "IEC 61215", "MQT 14.1", "Retention of J-box on mounting surface", "4.2.6/4.3.10")
        if p.get("electrical_attachment_change", False):
            add_test(plan, "IEC 61215", "MQT 11-200", "Thermal cycling 200 (electrical attachment changed)", "4.2.6")
        add_test(plan, "IEC 61215", "MQT 13", "Damp heat (termination)", "4.2.6/4.3.10")
        if not p.get("attachment_changes_only", False):
            add_test(plan, "IEC 61215", "MQT 18", "Bypass diode thermal (if applicable)", "4.2.6")

    if include_61730:
        if not p.get("jb_not_sun_exposed", False) and not p.get("potting_change_only", False):
            add_test(plan, "IEC 61730", "MST 54", "UV (termination)", "4.2.6/4.3.10")
        add_test(plan, "IEC 61730", "MST 51-50", "Thermal cycling 50", "4.2.6/4.3.10")
        add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.2.6/4.3.10")
        add_test(plan, "IEC 61730", "MST 42", "Robustness of terminations", "4.2.6/4.3.10")
        if p.get("electrical_attachment_change", False):
            add_test(plan, "IEC 61730", "MST 51-200", "Thermal cycling 200 (electrical attachment changed)", "4.2.6")
        add_test(plan, "IEC 61730", "MST 53", "Damp heat (termination)", "4.2.6/4.3.10")
        add_test(plan, "IEC 61730", "MST 11", "Accessibility", "4.2.6/4.3.10")
        if p.get("adhesive_change", False):
            add_test(plan, "IEC 61730", "MST 24", "Ignitability (adhesive change)", "4.2.6")
            add_sequence_flag(seq_flags, "SEQ_B", "4.2.6")
        if not p.get("adhesive_change", False):
            add_test(plan, "IEC 61730", "MST 26", "Reverse current overload", "4.2.6")
        if p.get("screw_connections_applicable", False):
            add_test(plan, "IEC 61730", "MST 33", "Screw connections test (if applicable)", "4.2.6")
        if p.get("cemented_joint", False):
            add_test(plan, "IEC 61730", "MST 35", "Peel test (cemented joint for JB attach)", "4.2.6")
            add_test(plan, "IEC 61730", "MST 36", "Lap shear (cemented joint for JB attach)", "4.2.6")
            add_test(plan, "IEC 61730", "MST 57", "Insulation coordination evaluation (cemented joint)", "4.2.6")
        if p.get("adhesive_change", False) or p.get("jb_weight_increase", False):
            add_test(plan, "IEC 61730", "MST 37", "Materials creep (adhesive / increased termination weight)", "4.2.6")
        if p.get("pollution_degree_1", False):
            add_sequence_flag(seq_flags, "SEQ_B1", "4.2.6")


def rules_bypass_diode(params, include_61215, include_61730, plan):
    """
    4.2.7 / 4.3.11 bypass diode
    Inputs: diode_rating_change, cells_per_diode_changed, diode_part_change, manufacturer_change,
            mounting_method_change
    """
    p = params
    if include_61215:
        if p.get("cells_per_diode_changed", False):
            add_test(plan, "IEC 61215", "MQT 09", "Hot-spot (cells per bypass diode changed)", "4.2.7/4.3.11")
        if p.get("mounting_method_change", False):
            add_test(plan, "IEC 61215", "MQT 11-200", "Thermal cycling 200 (diode mounting change)", "4.2.7/4.3.11")
        add_test(plan, "IEC 61215", "MQT 18", "Bypass diode thermal", "4.2.7/4.3.11")
    if include_61730:
        if p.get("cells_per_diode_changed", False):
            add_test(plan, "IEC 61730", "MST 22", "Hot-spot (cells per bypass diode changed)", "4.2.7/4.3.11")
        if p.get("mounting_method_change", False):
            add_test(plan, "IEC 61730", "MST 51-200", "Thermal cycling 200 (diode mounting change)", "4.2.7/4.3.11")
        add_test(plan, "IEC 61730", "MST 25", "Bypass diode thermal", "4.2.7/4.3.11")
        if p.get("mounting_method_change", False):
            add_test(plan, "IEC 61730", "MST 26", "Reverse current overload (mounting change)", "4.2.7/4.3.11")


def rules_electrical_circuitry_wbt(params, include_61215, include_61730, plan):
    """
    4.2.8 WBT: electrical circuitry (rerouting, reconfiguration)
    Inputs: more_cells_per_diode, internal_conductors_behind_cells, isc_increase_pct, reroute_output_leads, polymeric_outer
    """
    p = params
    if include_61215:
        if p.get("more_cells_per_diode", False):
            add_test(plan, "IEC 61215", "MQT 09", "Hot-spot (more cells per diode)", "4.2.8")
        if p.get("internal_conductors_behind_cells", False):
            add_test(plan, "IEC 61215", "MQT 11-200", "Thermal cycling 200 (internal conductors behind cells)", "4.2.8")
        if p.get("isc_increase_pct", 0.0) > 10.0:
            add_test(plan, "IEC 61215", "MQT 18", "Bypass diode thermal (Isc increased >10%)", "4.2.8")
    if include_61730:
        if p.get("more_cells_per_diode", False):
            add_test(plan, "IEC 61730", "MST 22", "Hot-spot (more cells per diode)", "4.2.8")
        if p.get("internal_conductors_behind_cells", False):
            add_test(plan, "IEC 61730", "MST 51-200", "Thermal cycling 200 (internal conductors behind cells)", "4.2.8")
        if p.get("isc_increase_pct", 0.0) > 10.0:
            add_test(plan, "IEC 61730", "MST 25", "Bypass diode thermal (Isc increased >10%)", "4.2.8")
        if p.get("reroute_output_leads", False) and p.get("polymeric_outer", False):
            add_test(plan, "IEC 61730", "MST 12", "Cut susceptibility (rerouted leads / polymeric outer)", "4.2.8")
            add_test(plan, "IEC 61730", "MST 04", "Insulation thickness (rerouted leads / polymeric outer)", "4.2.8")
        if p.get("operating_v_or_i_increase_pct", 0.0) >= 10.0:
            add_test(plan, "IEC 61730", "MST 26", "Reverse current overload (V/I increase ≥10%)", "4.2.8")


def rules_edge_seal(params, include_61215, include_61730, seq_flags, plan):
    """
    4.2.9 / 4.3.12 edge sealing
    Inputs: diff_material, thickness_or_width_change, outer_enclosure (bool)
    """
    p = params
    if include_61215:
        if p.get("outer_enclosure", False):
            add_test(plan, "IEC 61215", "MQT 10", "UV (edge seal outer enclosure)", "4.2.9/4.3.12")
            add_test(plan, "IEC 61215", "MQT 11-50", "TC 50 (edge seal outer enclosure)", "4.2.9/4.3.12")
            add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.9/4.3.12")
        add_test(plan, "IEC 61215", "MQT 13", "Damp heat", "4.2.9/4.3.12")
    if include_61730:
        if p.get("outer_enclosure", False):
            add_test(plan, "IEC 61730", "MST 54", "UV (edge seal outer enclosure)", "4.2.9/4.3.12")
            add_test(plan, "IEC 61730", "MST 51-50", "TC 50 (edge seal outer enclosure)", "4.2.9/4.3.12")
            add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.2.9/4.3.12")
        add_test(plan, "IEC 61730", "MST 53", "Damp heat", "4.2.9/4.3.12")
        add_test(plan, "IEC 61730", "MST 14", "Impulse voltage", "4.2.9/4.3.12")
        if p.get("diff_material", False):
            add_test(plan, "IEC 61730", "MST 24", "Ignitability (if accessible for flame)", "4.2.9/4.3.12")
            add_test(plan, "IEC 61730", "MST 35", "Peel test (cemented joint, if applicable)", "4.2.9/4.3.12")
            add_test(plan, "IEC 61730", "MST 36", "Lap shear (cemented joint, if applicable)", "4.2.9/4.3.12")
            add_sequence_flag(seq_flags, "SEQ_B", "4.2.9/4.3.12")


def rules_frame_mounting(params, include_61215, include_61730, plan):
    """
    4.2.10 / 4.3.13 frame and mounting structure
    Inputs: frame_material_change, frame_section_modulus_change_ge10, glass_capture_reduction_ge20,
            contact_surface_reduction_ge20, adhesive_change, polymeric_frame_change, framed_to_frameless,
            mounting_method_change, equipotential_bonding_change, coating_change_gt25, flexible, nonpolymeric_to_polymeric
    """
    p = params

    if include_61215:
        # UV + DynML + TC50 + HF only for changes in frame adhesive or polymeric mounting
        if p.get("adhesive_change", False) or p.get("polymeric_frame_change", False):
            add_test(plan, "IEC 61215", "MQT 10", "UV (frame/mounting, if adhesive exposed)", "4.2.10/4.3.13")
            add_test(plan, "IEC 61215", "MQT 20", "Dyn. mechanical load", "4.2.10/4.3.13")
            add_test(plan, "IEC 61215", "MQT 11-50", "TC 50", "4.2.10/4.3.13")
            add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.10/4.3.13")
        if p.get("adhesive_change", False) or p.get("polymeric_frame_change", False) or p.get("framed_to_frameless", False):
            add_test(plan, "IEC 61215", "MQT 13", "Damp heat", "4.2.10/4.3.13")
        add_test(plan, "IEC 61215", "MQT 16", "Static mechanical load (frame/mount)", "4.2.10/4.3.13")
        if p.get("nonpolymeric_to_polymeric", False) or p.get("framed_to_frameless", False):
            add_test(plan, "IEC 61215", "MQT 17", "Hail (frame change as specified)", "4.2.10")

    if include_61730:
        if p.get("adhesive_change", False) or p.get("polymeric_frame_change", False):
            add_test(plan, "IEC 61730", "MST 54", "UV (frame/adhesive, if exposed)", "4.2.10/4.3.13")
            add_test(plan, "IEC 61730", "MST 51-50", "TC 50", "4.2.10/4.3.13")
            add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.2.10/4.3.13")
        if p.get("adhesive_change", False) or p.get("polymeric_frame_change", False) or p.get("framed_to_frameless", False):
            add_test(plan, "IEC 61730", "MST 53", "Damp heat", "4.2.10/4.3.13")
        add_test(plan, "IEC 61730", "MST 34", "Static mechanical load (frame/mount)", "4.2.10/4.3.13")
        if p.get("equipotential_bonding_change", False):
            add_test(plan, "IEC 61730", "MST 13", "Continuity of equipotential bonding", "4.2.10/4.3.13")
        if p.get("polymeric_frame_change", False) or p.get("adhesive_change", False):
            add_test(plan, "IEC 61730", "MST 24", "Ignitability (polymeric frame/adhesive)", "4.2.10/4.3.13")
        add_test(plan, "IEC 61730", "MST 32", "Module breakage (frame)", "4.2.10/4.3.13")
        if p.get("screw_connections_applicable", False):
            add_test(plan, "IEC 61730", "MST 33", "Screw connections", "4.2.10/4.3.13")
        if p.get("creep_not_prevented_anymore", False):
            add_test(plan, "IEC 61730", "MST 37", "Materials creep", "4.2.10/4.3.13")


def rules_module_size(params, tech, include_61215, include_61730, plan):
    """
    4.2.11 / 4.3.14 module size
    Inputs: increase_pct (length/width/area)
    """
    inc = params.get("increase_pct", 0.0)
    if inc > 20.0:
        if include_61215:
            add_test(plan, "IEC 61215", "MQT 11-200", "Thermal cycling 200 (size increase >20%)", "4.2.11/4.3.14")
            add_test(plan, "IEC 61215", "MQT 13", "Damp heat (size increase)", "4.2.11/4.3.14")
            add_test(plan, "IEC 61215", "MQT 16", "Static mechanical load (size increase)", "4.2.11/4.3.14")
            if params.get("non_tempered_or_nonglass", False):
                add_test(plan, "IEC 61215", "MQT 17", "Hail (non-tempered or non-glass)", "4.2.11/4.3.14")
            if params.get("flexible_module", False):
                add_test(plan, "IEC 61215", "MQT 22", "Bending (flexible)", "4.2.11/4.3.14")
        if include_61730:
            add_test(plan, "IEC 61730", "MST 51-200", "Thermal cycling 200 (size increase >20%)", "4.2.11/4.3.14")
            add_test(plan, "IEC 61730", "MST 53", "Damp heat (size increase)", "4.2.11/4.3.14")
            add_test(plan, "IEC 61730", "MST 34", "Static mechanical load (size increase)", "4.2.11/4.3.14")
            add_test(plan, "IEC 61730", "MST 32", "Module breakage (size increase)", "4.2.11/4.3.14")


def rules_output_power_identical_size(params, include_61215, include_61730, plan):
    """
    4.2.12 / 4.3.15 Higher or lower power with identical design & size
    Inputs: delta_power_pct, isc_increase_pct
    """
    if include_61215:
        add_test(plan, "IEC 61215", "MQT 09", "Hot-spot (power change, identical size)", "4.2.12/4.3.15")
        if params.get("isc_increase_pct", 0.0) > 10.0:
            add_test(plan, "IEC 61215", "MQT 11-200", "Thermal cycling 200 (Isc increase >10%)", "4.2.12/4.3.15")
            add_test(plan, "IEC 61215", "MQT 18", "Bypass diode thermal (Isc increase >10%)", "4.2.12/4.3.15")
    if include_61730:
        add_test(plan, "IEC 61730", "MST 22", "Hot-spot (power change)", "4.2.12/4.3.15")
        if params.get("isc_increase_pct", 0.0) > 10.0:
            add_test(plan, "IEC 61730", "MST 51-200", "Thermal cycling 200 (Isc increase >10%)", "4.2.12/4.3.15")
            add_test(plan, "IEC 61730", "MST 25", "Bypass diode thermal (Isc increase >10%)", "4.2.12/4.3.15")
        add_test(plan, "IEC 61730", "MST 26", "Reverse current overload", "4.2.12/4.3.15")


def rules_ocp_increase(params, include_61730, plan):
    """
    4.2.13 / 4.3.16 Increase of over-current protection rating
    Inputs: ocp_increased (bool)
    """
    if include_61730 and params.get("ocp_increased", False):
        add_test(plan, "IEC 61730", "MST 13", "Continuity of equipotential bonding (OCP increase)", "4.2.13/4.3.16")
        add_test(plan, "IEC 61730", "MST 26", "Reverse current overload (OCP increase)", "4.2.13/4.3.16")


def rules_system_voltage_increase(params, include_61215, include_61730, seq_flags, plan):
    """
    4.2.14 / 4.3.17 Increase of system voltage by >5%
    Inputs: increased_by_gt5 (bool), non_glass_outer (bool)
    """
    if not params.get("increased_by_gt5", False):
        return
    if include_61215:
        add_test(plan, "IEC 61215", "MQT 09", "Hot-spot (system voltage increased)", "4.2.14/4.3.17")
        add_test(plan, "IEC 61215", "MQT 10", "UV preconditioning", "4.2.14/4.3.17")
        add_test(plan, "IEC 61215", "MQT 20", "Dyn. mechanical load", "4.2.14/4.3.17")
        add_test(plan, "IEC 61215", "MQT 11-50", "TC 50", "4.2.14/4.3.17")
        add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.14/4.3.17")
        add_test(plan, "IEC 61215", "MQT 11-200", "TC 200", "4.2.14/4.3.17")
        add_test(plan, "IEC 61215", "MQT 13", "Damp heat", "4.2.14/4.3.17")
        add_test(plan, "IEC 61215", "MQT 21", "PID", "4.2.14/4.3.17")
    if include_61730:
        add_note(plan, "Re-evaluate creepage/clearance per IEC 61730-1 (inspection/testing).")
        add_test(plan, "IEC 61730", "MST 22", "Hot-spot (system voltage increased)", "4.2.14/4.3.17")
        add_test(plan, "IEC 61730", "MST 54", "UV", "4.2.14/4.3.17")
        add_test(plan, "IEC 61730", "MST 51-50", "TC 50", "4.2.14/4.3.17")
        add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.2.14/4.3.17")
        add_test(plan, "IEC 61730", "MST 51-200", "TC 200", "4.2.14/4.3.17")
        add_test(plan, "IEC 61730", "MST 53", "Damp heat", "4.2.14/4.3.17")
        add_test(plan, "IEC 61730", "MST 04", "Insulation thickness", "4.2.14/4.3.17")
        add_test(plan, "IEC 61730", "MST 11", "Accessibility", "4.2.14/4.3.17")
        if params.get("non_glass_outer", False):
            add_test(plan, "IEC 61730", "MST 12", "Cut susceptibility (non-glass)", "4.2.14/4.3.17")
        add_test(plan, "IEC 61730", "MST 13", "Continuity of equipotential bonding", "4.2.14/4.3.17")
        add_test(plan, "IEC 61730", "MST 14", "Impulse voltage", "4.2.14/4.3.17")
        add_sequence_flag(seq_flags, "SEQ_B", "4.2.14/4.3.17")


def rules_cell_fixing_internal_tape_wbt(params, include_61215, plan):
    """
    4.2.15 WBT: cell fixing or internal insulation tape
    Inputs: diff_material_or_manufacturer (bool)
    """
    if include_61215 and params.get("diff_material_or_manufacturer", False):
        add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze (cell fixing/internal tape)", "4.2.15")


def rules_label_material(params, include_61730, seq_flags, plan):
    """
    4.2.16 / 4.3.18 label material
    Inputs: diff_label_or_ink_or_adhesive, side_has_label_exposed_to_uv, coupon_ok
    """
    p = params
    if include_61730 and p.get("diff_label_or_ink_or_adhesive", False):
        # Sequence B (omit UV on unlabeled side) – can be done on module or coupon
        add_test(plan, "IEC 61730", "MST 05", "Durability of markings", "4.2.16/4.3.18")
        add_sequence_flag(seq_flags, "SEQ_B", "4.2.16/4.3.18")


def rules_monofacial_to_bifacial(params, include_61215, include_61730, plan):
    """
    4.2.17 / 4.3.19 monofacial to bifacial
    Inputs: changed_substrate_transparency, changed_rear_encapsulant_transparency, changed_to_bifacial_cell,
            glass_backsheet_design, include_tc50_block (if 4.2.3 not already applied)
    """
    p = params
    if include_61215:
        if p.get("include_tc50_block", True):
            add_test(plan, "IEC 61215", "MQT 10", "UV", "4.2.17/4.3.19")
            add_test(plan, "IEC 61215", "MQT 20", "Dyn. mech. load", "4.2.17/4.3.19")
            add_test(plan, "IEC 61215", "MQT 11-50", "TC 50", "4.2.17/4.3.19")
            add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.17/4.3.19")
        add_test(plan, "IEC 61215", "MQT 11-200", "TC 200", "4.2.17/4.3.19")
        add_test(plan, "IEC 61215", "MQT 04", "Temperature coefficients", "4.2.17/4.3.19")
        add_test(plan, "IEC 61215", "MQT 07", "Performance at low irradiance", "4.2.17/4.3.19")
        add_test(plan, "IEC 61215", "MQT 09", "Hot-spot", "4.2.17/4.3.19")
        add_test(plan, "IEC 61215", "MQT 18.1", "Bypass diode thermal (bifacial)", "4.2.17/4.3.19")
        if p.get("glass_backsheet", False):
            add_test(plan, "IEC 61215", "MQT 21", "PID (glass backsheet)", "4.2.17/4.3.19")
    if include_61730:
        add_test(plan, "IEC 61730", "MST 22", "Hot-spot", "4.2.17/4.3.19")
        add_test(plan, "IEC 61730", "MST 54", "UV", "4.2.17/4.3.19")
        add_test(plan, "IEC 61730", "MST 51-50", "TC 50", "4.2.17/4.3.19")
        add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.2.17/4.3.19")
        add_test(plan, "IEC 61730", "MST 25", "Bypass diode thermal", "4.2.17/4.3.19")
        add_test(plan, "IEC 61730", "MST 51-200", "TC 200", "4.2.17/4.3.19")
        add_test(plan, "IEC 61730", "MST 26", "Reverse current overload", "4.2.17/4.3.19")
        add_test(plan, "IEC 61730", "MST 13", "Continuity of equipotential bonding", "4.2.17/4.3.19")


def rules_operating_temperature(params, plan):
    """
    4.2.18 / 4.3.20 module operating temperature increase
    Inputs: t98_increase, qualifying_to_level ('none'/'level1'/'level2')
    """
    if params.get("qualifying_to_level", "none") in ("level1", "level2"):
        add_note(plan, "Re-run sequences at modified temperatures per IEC TS 63126 for high-temperature operation. (4.2.18/4.3.20)")
        # Construction requirements must be re-evaluated per TS 63126.


def rules_mli_front_back_contact_edge_deletion_interconnect(params, include_61215, include_61730, plan):
    """
    4.3.3, 4.3.6, 4.3.7, 4.3.8 for MLI thin-film specifics
    Inputs booleans: mli_front_contact_change, mli_back_contact_change, mli_edge_deletion_change,
                     mli_interconnect_change, isc_increase_pct, cemented_joint
    """
    p = params

    if p.get("mli_front_contact_change", False):
        if include_61215:
            add_test(plan, "IEC 61215", "MQT 09", "Hot-spot (MLI front contact)", "4.3.3")
            add_test(plan, "IEC 61215", "MQT 10", "UV", "4.3.3")
            add_test(plan, "IEC 61215", "MQT 20", "Dyn ML", "4.3.3")
            add_test(plan, "IEC 61215", "MQT 11-50", "TC 50", "4.3.3")
            add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.3.3")
            add_test(plan, "IEC 61215", "MQT 13", "Damp heat", "4.3.3")
        if include_61730:
            add_test(plan, "IEC 61730", "MST 22", "Hot-spot (MLI front contact)", "4.3.3")
            add_test(plan, "IEC 61730", "MST 54", "UV", "4.3.3")
            add_test(plan, "IEC 61730", "MST 51-50", "TC 50", "4.3.3")
            add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.3.3")
            add_test(plan, "IEC 61730", "MST 53", "Damp heat", "4.3.3")
            add_test(plan, "IEC 61730", "MST 14", "Impulse voltage", "4.3.3")
            add_test(plan, "IEC 61730", "MST 26", "Reverse current overload", "4.3.3")

    if p.get("mli_back_contact_change", False):
        if include_61215:
            add_test(plan, "IEC 61215", "MQT 09", "Hot-spot (MLI back contact)", "4.3.6")
            add_test(plan, "IEC 61215", "MQT 20", "Dyn ML", "4.3.6")
            add_test(plan, "IEC 61215", "MQT 11-50", "TC 50", "4.3.6")
            add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.3.6")
            add_test(plan, "IEC 61215", "MQT 13", "Damp heat", "4.3.6")
        if include_61730:
            add_test(plan, "IEC 61730", "MST 22", "Hot-spot (MLI back contact)", "4.3.6")
            add_test(plan, "IEC 61730", "MST 51-50", "TC 50", "4.3.6")
            add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.3.6")
            add_test(plan, "IEC 61730", "MST 53", "Damp heat", "4.3.6")
            add_test(plan, "IEC 61730", "MST 14", "Impulse voltage", "4.3.6")
            add_test(plan, "IEC 61730", "MST 26", "Reverse current overload", "4.3.6")

    if p.get("mli_edge_deletion_change", False):
        if include_61215:
            add_test(plan, "IEC 61215", "MQT 20", "Dyn ML", "4.3.7")
            add_test(plan, "IEC 61215", "MQT 11-50", "TC 50", "4.3.7")
            add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.3.7")
            add_test(plan, "IEC 61215", "MQT 13", "Damp heat", "4.3.7")
        if include_61730:
            add_test(plan, "IEC 61730", "MST 51-50", "TC 50", "4.3.7")
            add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.3.7")
            add_test(plan, "IEC 61730", "MST 53", "Damp heat", "4.3.7")
            add_test(plan, "IEC 61730", "MST 14", "Impulse voltage", "4.3.7")
            if p.get("cemented_joint", False):
                add_test(plan, "IEC 61730", "MST 35", "Peel test (cemented joint)", "4.3.7")
                add_test(plan, "IEC 61730", "MST 36", "Lap shear (cemented joint)", "4.3.7")

    if p.get("mli_interconnect_change", False):
        if include_61215:
            add_test(plan, "IEC 61215", "MQT 11-200", "TC 200 (MLI interconnect)", "4.3.8")
            if p.get("material_change", False):
                add_test(plan, "IEC 61215", "MQT 13", "Damp heat (material change)", "4.3.8")
        if include_61730:
            add_test(plan, "IEC 61730", "MST 51-200", "TC 200 (MLI interconnect)", "4.3.8")
            if p.get("material_change", False):
                add_test(plan, "IEC 61730", "MST 53", "Damp heat (material change)", "4.3.8")
            add_test(plan, "IEC 61730", "MST 26", "Reverse current overload", "4.3.8")


# -----------------------
# UI
# -----------------------

st.title("IEC TS 62915:2023 — Retesting Planner (Decision Support)")
st.caption("This tool encodes key decision logic from IEC TS 62915:2023 to propose retest programs for modified PV modules. Final review is required by qualified engineers.")

with st.sidebar:
    st.header("Program Setup")
    tech = st.radio("Module technology", ["WBT (wafer-based)", "MLI (thin-film monolithic)"])
    program = st.selectbox("Retest program scope", ["IEC 61215 only", "IEC 61730 only", "Combined IEC 61215 + IEC 61730"])
    include_61215 = program in ("IEC 61215 only", "Combined IEC 61215 + IEC 61730")
    include_61730 = program in ("IEC 61730 only", "Combined IEC 61215 + IEC 61730")

    st.markdown("---")
    st.subheader("Gate 1 / Gate 2 (61215)")
    gate_block = st.checkbox("Record Gate-1/Gate-2 (rating & relative power change) for 61215 retest")
    gate_input = {}
    if gate_block and include_61215:
        gate_input["rated_Pmp_W"] = st.number_input("Rated Pmp (W)", min_value=0.0, value=0.0, step=0.1)
        gate_input["measured_Pmp_W"] = st.number_input("Measured stabilized Pmp (W)", min_value=0.0, value=0.0, step=0.1)
        gate_input["measured_Voc_V"] = st.number_input("Measured stabilized Voc (V)", min_value=0.0, value=0.0, step=0.01)
        gate_input["measured_Isc_A"] = st.number_input("Measured stabilized Isc (A)", min_value=0.0, value=0.0, step=0.01)

    st.markdown("---")
    st.subheader("Retest Modifications")
    mods = st.multiselect(
        "Select all applicable design changes",
        [
            "Frontsheet",
            "Encapsulation",
            "Cell technology (WBT)",
            "Cell & string interconnect (WBT)",
            "Backsheet",
            "Electrical termination",
            "Bypass diode",
            "Electrical circuitry (WBT)",
            "Edge sealing",
            "Frame & mounting",
            "Module size increase",
            "Higher/lower output power (identical design & size)",
            "Increase OCP rating",
            "Increase system voltage (>5%)",
            "Cell fixing / internal insulation tape (WBT)",
            "Label material (external nameplate)",
            "Change to bifacial",
            "Operating temperature category increase (TS 63126)",
        ] + (
            ["MLI: Front contact", "MLI: Back contact", "MLI: Edge deletion", "MLI: Interconnect material/technique"]
            if tech.startswith("MLI") else []
        )
    )

# Parameter panels
params = {}

if "Frontsheet" in mods:
    with st.expander("Frontsheet parameters"):
        c1, c2, c3 = st.columns(3)
        with c1:
            params["frontsheet.material_type"] = st.selectbox("Frontsheet material", ["glass", "polymeric"])
            params["frontsheet.thickness_change_pct"] = st.number_input("Thickness change (%) vs ref (negative = reduction)", value=0.0, step=1.0)
            params["frontsheet.strengthening_change"] = st.checkbox("Glass strengthening process changed (tempered↔heat-strengthened/annealed)")
        with c2:
            params["frontsheet.surface_treatment_changed"] = st.checkbox("Surface treatment changed (inside/outside)")
            params["frontsheet.outside_surface_only"] = st.checkbox("Change only to outside surface treatment")
            params["frontsheet.ar_lambda_c_uv_change"] = st.selectbox("Glass λcUV vs previous", ["unknown", ">= previous", "< previous"])
        with c3:
            params["frontsheet.jb_on_frontsheet"] = st.checkbox("Junction box on frontsheet")
            params["frontsheet.flexible_module"] = st.checkbox("Module is flexible")
            params["frontsheet.cemented_joint"] = st.checkbox("Includes cemented joint")
            params["frontsheet.model_designation_change"] = st.checkbox("Polymeric model designation change (per IEC 62788-2-1)")
            params["frontsheet.glass_to_poly_or_vice_versa"] = st.checkbox("Glass ↔ Non-glass change")

if "Encapsulation" in mods:
    with st.expander("Encapsulation parameters"):
        c1, c2, c3 = st.columns(3)
        with c1:
            params["encap.different_material"] = st.checkbox("Different encapsulant material")
            params["encap.additives_change_same_material"] = st.checkbox("Additives change (same material, same manufacturer)")
            params["encap.thickness_change_pct"] = st.number_input("Single film thickness change (%) (neg=reduction)", value=0.0, step=1.0)
        with c2:
            params["encap.flexible_module"] = st.checkbox("Module flexible (per IEC 61215)")
            params["encap.frontsheet_polymeric"] = st.checkbox("Polymeric frontsheet used")
            params["encap.front_or_back_polymeric"] = st.checkbox("Front or back polymeric outer layer")
        with c3:
            params["encap.volume_resistivity_drop_order"] = st.number_input("Volume resistivity drop (orders of magnitude)", min_value=0, value=0, step=1)
            params["encap.material_changed_composition"] = st.checkbox("Material composition changed")
            params["encap.cemented_joint"] = st.checkbox("Encapsulant part of cemented joint")
            params["encap.pollution_degree_1"] = st.checkbox("Design qualified for pollution degree 1")

if "Cell technology (WBT)" in mods and tech.startswith("WBT"):
    with st.expander("Cell technology (WBT) parameters"):
        c1, c2 = st.columns(2)
        with c1:
            params["cell.tech_change"] = st.checkbox("Cell technology changed (e.g., PERC→TOPCon/HJT, mono↔poly)")
            params["cell.ar_change"] = st.checkbox("Anti-reflective coating changed")
            params["cell.crystallization_change"] = st.checkbox("Wafer crystallization changed (mono/poly/cast-mono)")
            params["cell.manufacturer_change"] = st.checkbox("Cell manufacturer/site change (not same QMS)")
        with c2:
            params["cell.cell_thickness_reduction_pct"] = st.number_input("Cell thickness change (%) (neg=reduction)", value=0.0, step=1.0)
            params["cell.cell_size_change_pct"] = st.number_input("Cell size change (% length/width/area)", value=0.0, step=1.0)
            params["cell.moved_to_half_cell"] = st.checkbox("Changed to cut/half-cells")

if "Cell & string interconnect (WBT)" in mods and tech.startswith("WBT"):
    with st.expander("Cell & string interconnect parameters"):
        c1, c2 = st.columns(2)
        with c1:
            params["ic.different_material"] = st.checkbox("Different interconnect material/chemistry/alloy/coating/core")
            params["ic.solder_flux_change"] = st.checkbox("Different solder paste/wire/flux or conductive adhesive")
        with c2:
            params["ic.bonding_tech_change"] = st.checkbox("Different bonding technique/equipment")
            params["ic.cross_section_change_pct"] = st.number_input("Change in total cross-section (%) (±)", value=0.0, step=1.0)

if "Backsheet" in mods:
    with st.expander("Backsheet parameters"):
        c1, c2, c3 = st.columns(3)
        with c1:
            params["backsheet.material_type"] = st.selectbox("Backsheet material", ["glass", "polymeric"])
            params["backsheet.thickness_change_pct"] = st.number_input("Thickness change (%) (neg=reduction)", value=0.0, step=1.0)
            params["backsheet.strengthening_change"] = st.checkbox("Glass strengthening process changed")
        with c2:
            params["backsheet.surface_treatment_changed"] = st.checkbox("Surface treatment changed (inside/outside)")
            params["backsheet.outside_surface_only"] = st.checkbox("Change only to outside surface")
            params["backsheet.jb_on_backsheet"] = st.checkbox("Junction box mounted on backsheet")
        with c3:
            params["backsheet.flexible_module"] = st.checkbox("Module flexible")
            params["backsheet.rigidity_depends_on_backsheet"] = st.checkbox("Rigidity depends on backsheet (e.g., glass backsheet)")
            params["backsheet.mounting_depends_on_backsheet"] = st.checkbox("Mounting depends on backsheet adhesion")
            params["backsheet.cemented_joint"] = st.checkbox("Backsheet part of cemented joint")
            params["backsheet.model_designation_change"] = st.checkbox("Polymeric model designation change (IEC 62788-2-1)")
            params["backsheet.pollution_degree_1"] = st.checkbox("Design qualified for pollution degree 1")

if "Electrical termination" in mods:
    with st.expander("Electrical termination parameters"):
        c1, c2, c3 = st.columns(3)
        with c1:
            params["term.potting_change_only"] = st.checkbox("Only potting material change")
            params["term.only_cable_or_connector_change"] = st.checkbox("Only cable/connector change")
            params["term.only_mech_attachment_or_num_jb"] = st.checkbox("Only mechanical attachment/number of JB changed")
        with c2:
            params["term.jb_prequalified"] = st.checkbox("Junction box pre-qualified (IEC 62790)")
            params["term.jb_not_sun_exposed"] = st.checkbox("JB not directly sun-exposed (omit UV)")
            params["term.electrical_attachment_change"] = st.checkbox("Electrical attachment changed (solder/crimp/braze)")
        with c3:
            params["term.adhesive_change"] = st.checkbox("Adhesive change for mechanical attachment")
            params["term.screw_connections_applicable"] = st.checkbox("Screw connections applicable")
            params["term.cemented_joint"] = st.checkbox("Design includes cemented joint for JB attachment")
            params["term.relocation_or_position_only"] = st.checkbox("Only relocation/position changed")
            params["term.jb_weight_increase"] = st.checkbox("Increased termination weight")
            params["term.pollution_degree_1"] = st.checkbox("Design qualified for pollution degree 1")

if "Bypass diode" in mods:
    with st.expander("Bypass diode parameters"):
        params["diode.cells_per_diode_changed"] = st.checkbox("Number of cells per diode changed")
        params["diode.mounting_method_change"] = st.checkbox("Diode mounting method/process changed")

if "Electrical circuitry (WBT)" in mods and tech.startswith("WBT"):
    with st.expander("Electrical circuitry (WBT) parameters"):
        c1, c2 = st.columns(2)
        with c1:
            params["circ.more_cells_per_diode"] = st.checkbox("More cells per bypass diode")
            params["circ.internal_conductors_behind_cells"] = st.checkbox("Internal conductors behind cells present")
        with c2:
            params["circ.isc_increase_pct"] = st.number_input("Isc increase (%)", value=0.0, step=1.0)
            params["circ.operating_v_or_i_increase_pct"] = st.number_input("Operating V/I increase (%)", value=0.0, step=1.0)
            params["circ.reroute_output_leads"] = st.checkbox("Reroute output leads")
            params["circ.polymeric_outer"] = st.checkbox("Polymeric frontsheet/backsheet present")

if "Edge sealing" in mods:
    with st.expander("Edge sealing parameters"):
        params["edge.diff_material"] = st.checkbox("Different edge seal material")
        params["edge.thickness_or_width_change"] = st.checkbox("Different thickness or width")
        params["edge.outer_enclosure"] = st.checkbox("Edge seal is outer enclosure")

if "Frame & mounting" in mods:
    with st.expander("Frame & mounting parameters"):
        c1, c2, c3 = st.columns(3)
        with c1:
            params["frame.adhesive_change"] = st.checkbox("Frame/mount adhesive change")
            params["frame.polymeric_frame_change"] = st.checkbox("Polymeric frame change")
            params["frame.framed_to_frameless"] = st.checkbox("Change framed ↔ frameless")
        with c2:
            params["frame.equipotential_bonding_change"] = st.checkbox("Equipotential bonding method change")
            params["frame.screw_connections_applicable"] = st.checkbox("Screw connections applicable")
            params["frame.creep_not_prevented_anymore"] = st.checkbox("Support no longer prevents creep")
        with c3:
            params["frame.nonpolymeric_to_polymeric"] = st.checkbox("Change from non-polymeric to polymeric frame")
            params["frame.mounting_method_change"] = st.checkbox("Different mounting method (per manual)")

if "Module size increase" in mods:
    with st.expander("Module size parameters"):
        params["size.increase_pct"] = st.number_input("Increase in length/width/area (%)", value=0.0, step=1.0)
        params["size.non_tempered_or_nonglass"] = st.checkbox("Non-tempered glass or non-glass used")
        params["size.flexible_module"] = st.checkbox("Module flexible")

if "Higher/lower output power (identical design & size)" in mods:
    with st.expander("Output power change parameters"):
        params["pwr.delta_power_pct"] = st.number_input("Δ Power (%) (info)", value=0.0, step=0.1)
        params["pwr.isc_increase_pct"] = st.number_input("Isc increase (%)", value=0.0, step=0.1)

if "Increase OCP rating" in mods:
    with st.expander("OCP rating parameters"):
        params["ocp.ocp_increased"] = st.checkbox("Over-current protection rating increased")

if "Increase system voltage (>5%)" in mods:
    with st.expander("System voltage increase parameters"):
        params["vsys.increased_by_gt5"] = st.checkbox("System voltage increased by >5%")
        params["vsys.non_glass_outer"] = st.checkbox("Module has non-glass outer surface")

if "Cell fixing / internal insulation tape (WBT)" in mods and tech.startswith("WBT"):
    with st.expander("Cell fixing / internal insulation tape parameters"):
        params["tape.diff_material_or_manufacturer"] = st.checkbox("Different material/manufacturer")

if "Label material (external nameplate)" in mods:
    with st.expander("Label parameters"):
        params["label.diff_label_or_ink_or_adhesive"] = st.checkbox("Different label / ink / adhesive")
        params["label.side_has_label_exposed_to_uv"] = st.checkbox("Label side exposed to UV")
        params["label.coupon_ok"] = st.checkbox("Coupon testing instead of full module acceptable")

if "Change to bifacial" in mods:
    with st.expander("Bifacial parameters"):
        params["bif.include_tc50_block"] = st.checkbox("Include TC50 block (if 4.2.3 not already applied)", value=True)
        params["bif.glass_backsheet"] = st.checkbox("Design includes glass backsheet")

if "Operating temperature category increase (TS 63126)" in mods:
    with st.expander("Operating temperature parameters"):
        params["temp.qualifying_to_level"] = st.selectbox("Qualify for higher operating temperature", ["none", "level1", "level2"])

if "MLI: Front contact" in mods or "MLI: Back contact" in mods or "MLI: Edge deletion" in mods or "MLI: Interconnect material/technique" in mods:
    with st.expander("MLI thin-film specifics"):
        params["mli.front_contact_change"] = st.checkbox("Front contact change (TCO etc.)", value=("MLI: Front contact" in mods))
        params["mli.back_contact_change"] = st.checkbox("Back contact change", value=("MLI: Back contact" in mods))
        params["mli.edge_deletion_change"] = st.checkbox("Edge deletion process/width change", value=("MLI: Edge deletion" in mods))
        params["mli.interconnect_change"] = st.checkbox("Interconnect material/technique change", value=("MLI: Interconnect material/technique" in mods))
        params["mli.material_change"] = st.checkbox("Interconnect material change (MLI)")
        params["mli.cemented_joint"] = st.checkbox("Cemented joint present")
        params["mli.isc_increase_pct"] = st.number_input("Isc increase (%) (MLI context)", value=0.0, step=0.1)

# -----------------------
# Compute retest plan
# -----------------------

if st.button("Generate Retest Plan"):
    plan = {}
    seq_flags = set()

    # Baseline (4.1)
    baseline_checks(include_61215, include_61730, plan)

    # Gate info (record only)
    gate_results = {}
    if gate_block and include_61215:
        rated = gate_input.get("rated_Pmp_W", 0.0)
        meas = gate_input.get("measured_Pmp_W", 0.0)
        delta = (meas - rated) / rated * 100.0 if rated > 0 else None
        gate_results = {
            "Rated_Pmp_W": rated,
            "Measured_Pmp_W": meas,
            "Delta_Pmp_%": delta,
            "Measured_Voc_V": gate_input.get("measured_Voc_V", 0.0),
            "Measured_Isc_A": gate_input.get("measured_Isc_A", 0.0)
        }
        add_note(plan, f"Gate-1/2 recorded: ΔPmp%={delta:.2f}% (engineer to assess per IEC 61215-1).")

    # Apply rules per selected modifications
    # Frontsheet
    if "Frontsheet" in mods:
        rules_frontsheet(
            {
                "material_type": params.get("frontsheet.material_type"),
                "thickness_change_pct": params.get("frontsheet.thickness_change_pct"),
                "surface_treatment_changed": params.get("frontsheet.surface_treatment_changed"),
                "outside_surface_only": params.get("frontsheet.outside_surface_only"),
                "ar_lambda_c_uv_change": params.get("frontsheet.ar_lambda_c_uv_change"),
                "strengthening_change": params.get("frontsheet.strengthening_change"),
                "jb_on_frontsheet": params.get("frontsheet.jb_on_frontsheet"),
                "flexible_module": params.get("frontsheet.flexible_module"),
                "cemented_joint": params.get("frontsheet.cemented_joint"),
                "model_designation_change": params.get("frontsheet.model_designation_change"),
                "glass_to_poly_or_vice_versa": params.get("frontsheet.glass_to_poly_or_vice_versa"),
            },
            tech, include_61215, include_61730, seq_flags, plan
        )

    # Encapsulation
    if "Encapsulation" in mods:
        rules_encapsulation(
            {
                "different_material": params.get("encap.different_material"),
                "additives_change_same_material": params.get("encap.additives_change_same_material"),
                "thickness_change_pct": params.get("encap.thickness_change_pct"),
                "flexible_module": params.get("encap.flexible_module"),
                "frontsheet_polymeric": params.get("encap.frontsheet_polymeric"),
                "front_or_back_polymeric": params.get("encap.front_or_back_polymeric"),
                "volume_resistivity_drop_order": params.get("encap.volume_resistivity_drop_order"),
                "material_changed_composition": params.get("encap.material_changed_composition"),
                "cemented_joint": params.get("encap.cemented_joint"),
                "pollution_degree_1": params.get("encap.pollution_degree_1"),
            },
            tech, include_61215, include_61730, seq_flags, plan
        )

    # Cell technology (WBT)
    if "Cell technology (WBT)" in mods and tech.startswith("WBT"):
        rules_cell_technology_wbt(
            {
                "tech_change": params.get("cell.tech_change"),
                "ar_change": params.get("cell.ar_change"),
                "crystallization_change": params.get("cell.crystallization_change"),
                "manufacturer_change": params.get("cell.manufacturer_change"),
                "cell_thickness_reduction_pct": params.get("cell.cell_thickness_reduction_pct"),
                "cell_size_change_pct": params.get("cell.cell_size_change_pct"),
                "moved_to_half_cell": params.get("cell.moved_to_half_cell"),
            },
            include_61215, include_61730, plan
        )

    # Cell & string interconnect (WBT)
    if "Cell & string interconnect (WBT)" in mods and tech.startswith("WBT"):
        rules_interconnect_wbt(
            {
                "different_material": params.get("ic.different_material"),
                "solder_flux_change": params.get("ic.solder_flux_change"),
                "bonding_tech_change": params.get("ic.bonding_tech_change"),
                "cross_section_change_pct": params.get("ic.cross_section_change_pct"),
            },
            include_61215, include_61730, plan
        )

    # Backsheet
    if "Backsheet" in mods:
        rules_backsheet(
            {
                "material_type": params.get("backsheet.material_type"),
                "thickness_change_pct": params.get("backsheet.thickness_change_pct"),
                "surface_treatment_changed": params.get("backsheet.surface_treatment_changed"),
                "outside_surface_only": params.get("backsheet.outside_surface_only"),
                "jb_on_backsheet": params.get("backsheet.jb_on_backsheet"),
                "flexible_module": params.get("backsheet.flexible_module"),
                "rigidity_depends_on_backsheet": params.get("backsheet.rigidity_depends_on_backsheet"),
                "mounting_depends_on_backsheet": params.get("backsheet.mounting_depends_on_backsheet"),
                "cemented_joint": params.get("backsheet.cemented_joint"),
                "model_designation_change": params.get("backsheet.model_designation_change"),
                "pollution_degree_1": params.get("backsheet.pollution_degree_1"),
                "strengthening_change": params.get("backsheet.strengthening_change"),
            },
            tech, include_61215, include_61730, seq_flags, plan
        )

    # Electrical termination
    if "Electrical termination" in mods:
        rules_electrical_termination(
            {
                "potting_change_only": params.get("term.potting_change_only"),
                "only_cable_or_connector_change": params.get("term.only_cable_or_connector_change"),
                "only_mech_attachment_or_num_jb": params.get("term.only_mech_attachment_or_num_jb"),
                "jb_prequalified": params.get("term.jb_prequalified"),
                "jb_not_sun_exposed": params.get("term.jb_not_sun_exposed"),
                "electrical_attachment_change": params.get("term.electrical_attachment_change"),
                "adhesive_change": params.get("term.adhesive_change"),
                "screw_connections_applicable": params.get("term.screw_connections_applicable"),
                "cemented_joint": params.get("term.cemented_joint"),
                "relocation_or_position_only": params.get("term.relocation_or_position_only"),
                "jb_weight_increase": params.get("term.jb_weight_increase"),
                "pollution_degree_1": params.get("term.pollution_degree_1"),
            },
            include_61215, include_61730, seq_flags, plan
        )

    # Bypass diode
    if "Bypass diode" in mods:
        rules_bypass_diode(
            {
                "cells_per_diode_changed": params.get("diode.cells_per_diode_changed"),
                "mounting_method_change": params.get("diode.mounting_method_change"),
            },
            include_61215, include_61730, plan
        )

    # Electrical circuitry (WBT)
    if "Electrical circuitry (WBT)" in mods and tech.startswith("WBT"):
        rules_electrical_circuitry_wbt(
            {
                "more_cells_per_diode": params.get("circ.more_cells_per_diode"),
                "internal_conductors_behind_cells": params.get("circ.internal_conductors_behind_cells"),
                "isc_increase_pct": params.get("circ.isc_increase_pct"),
                "reroute_output_leads": params.get("circ.reroute_output_leads"),
                "polymeric_outer": params.get("circ.polymeric_outer"),
                "operating_v_or_i_increase_pct": params.get("circ.operating_v_or_i_increase_pct"),
            },
            include_61215, include_61730, plan
        )

    # Edge sealing
    if "Edge sealing" in mods:
        rules_edge_seal(
            {
                "diff_material": params.get("edge.diff_material"),
                "thickness_or_width_change": params.get("edge.thickness_or_width_change"),
                "outer_enclosure": params.get("edge.outer_enclosure"),
            },
            include_61215, include_61730, seq_flags, plan
        )

    # Frame & mounting
    if "Frame & mounting" in mods:
        rules_frame_mounting(
            {
                "adhesive_change": params.get("frame.adhesive_change"),
                "polymeric_frame_change": params.get("frame.polymeric_frame_change"),
                "framed_to_frameless": params.get("frame.framed_to_frameless"),
                "equipotential_bonding_change": params.get("frame.equipotential_bonding_change"),
                "screw_connections_applicable": params.get("frame.screw_connections_applicable"),
                "creep_not_prevented_anymore": params.get("frame.creep_not_prevented_anymore"),
                "nonpolymeric_to_polymeric": params.get("frame.nonpolymeric_to_polymeric"),
                "mounting_method_change": params.get("frame.mounting_method_change"),
            },
            include_61215, include_61730, plan
        )

    # Module size
    if "Module size increase" in mods:
        rules_module_size(
            {
                "increase_pct": params.get("size.increase_pct", 0.0),
                "non_tempered_or_nonglass": params.get("size.non_tempered_or_nonglass", False),
                "flexible_module": params.get("size.flexible_module", False)
            },
            tech, include_61215, include_61730, plan
        )

    # Output power (identical design & size)
    if "Higher/lower output power (identical design & size)" in mods:
        rules_output_power_identical_size(
            {
                "delta_power_pct": params.get("pwr.delta_power_pct", 0.0),
                "isc_increase_pct": params.get("pwr.isc_increase_pct", 0.0),
            },
            include_61215, include_61730, plan
        )

    # OCP rating
    if "Increase OCP rating" in mods:
        rules_ocp_increase(
            {"ocp_increased": params.get("ocp.ocp_increased", False)},
            include_61730, plan
        )

    # System voltage increase
    if "Increase system voltage (>5%)" in mods:
        rules_system_voltage_increase(
            {
                "increased_by_gt5": params.get("vsys.increased_by_gt5", False),
                "non_glass_outer": params.get("vsys.non_glass_outer", False),
            },
            include_61215, include_61730, seq_flags, plan
        )

    # Cell fixing / internal insulation tape (WBT)
    if "Cell fixing / internal insulation tape (WBT)" in mods and tech.startswith("WBT"):
        rules_cell_fixing_internal_tape_wbt(
            {"diff_material_or_manufacturer": params.get("tape.diff_material_or_manufacturer", False)},
            include_61215, plan
        )

    # Label material
    if "Label material (external nameplate)" in mods:
        rules_label_material(
            {
                "diff_label_or_ink_or_adhesive": params.get("label.diff_label_or_ink_or_adhesive", False),
                "side_has_label_exposed_to_uv": params.get("label.side_has_label_exposed_to_uv", False),
                "coupon_ok": params.get("label.coupon_ok", False),
            },
            include_61730, seq_flags, plan
        )

    # Monofacial to bifacial
    if "Change to bifacial" in mods:
        rules_monofacial_to_bifacial(
            {
                "include_tc50_block": params.get("bif.include_tc50_block", True),
                "glass_backsheet": params.get("bif.glass_backsheet", False),
            },
            include_61215, include_61730, plan
        )

    # Operating temperature category
    if "Operating temperature category increase (TS 63126)" in mods:
        rules_operating_temperature(
            {
                "qualifying_to_level": params.get("temp.qualifying_to_level", "none"),
            },
            plan
        )

    # MLI specifics
    if tech.startswith("MLI"):
        rules_mli_front_back_contact_edge_deletion_interconnect(
            {
                "mli_front_contact_change": params.get("mli.front_contact_change", False),
                "mli_back_contact_change": params.get("mli.back_contact_change", False),
                "mli_edge_deletion_change": params.get("mli.edge_deletion_change", False),
                "mli_interconnect_change": params.get("mli.interconnect_change", False),
                "material_change": params.get("mli.material_change", False),
                "cemented_joint": params.get("mli.cemented_joint", False),
                "isc_increase_pct": params.get("mli.isc_increase_pct", 0.0),
            },
            include_61215, include_61730, plan
        )

    # Collect tests into DataFrame
    tests = []
    notes = []
    for k, v in plan.items():
        if k == ("NOTES", "NOTES"):
            notes = v["NotesOnly"]
            continue
        reasons = "; ".join(sorted(v["Reasons"])) if v["Reasons"] else ""
        clauses = "; ".join(sorted(v["Clauses"])) if v["Clauses"] else ""
        tests.append({
            "Standard": v["Standard"],
            "Test ID": v["Test ID"],
            "Test name": v["Test name"],
            "Clause ref": clauses,
            "Reason(s)": reasons
        })
    df = pd.DataFrame(tests).sort_values(["Standard", "Test ID"]).reset_index(drop=True)

    st.success("Retest plan generated.")
    st.subheader("Proposed Retest Plan")
    st.dataframe(df, use_container_width=True)

    if notes:
        st.markdown("**Notes & Engineering Actions**")
        for n in notes:
            st.write("- " + n)

    # Sequence flags (61730) display
    if seq_flags:
        st.markdown("**Sequence Flags (IEC 61730)**")
        for flag, clause in sorted(seq_flags):
            st.write(f"- {SEQUENCE_FLAGS.get(flag, flag)} (ref: {clause})")

    # Optional mini flow graph (requires Graphviz)
    with st.expander("Show combined flow graph (compact)"):
        try:
            import graphviz
            dot = graphviz.Digraph()
            dot.attr(rankdir="LR", fontsize="10")
            # Baseline
            if include_61215:
                dot.node("BL15", "61215 Baseline\n(MQT01/03/06.1/15/19)")
            if include_61730:
                dot.node("BL30", "61730 Baseline\n(MST01/03/16/17)")
            # Sequences
            if include_61215:
                dot.node("SEQ15", "61215 Test Blocks")
            if include_61730:
                label = "61730 Sequences"
                if seq_flags:
                    label += "\n" + ", ".join(sorted([f for f,_ in seq_flags]))
                dot.node("SEQ30", label)
            # Connect
            if include_61215 and include_61730:
                dot.edge("BL15", "SEQ15")
                dot.edge("BL30", "SEQ30")
            elif include_61215:
                dot.edge("BL15", "SEQ15")
            else:
                dot.edge("BL30", "SEQ30")
            st.graphviz_chart(dot)
        except Exception:
            st.info("Graphviz not available. Install Graphviz to see the flow diagram.")

    # Downloads
    st.subheader("Download")
    def to_excel_bytes(df_, notes_, gate_):
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_.to_excel(writer, index=False, sheet_name="Retest Plan")
            # Summary sheet
            summary = pd.DataFrame({
                "Generated_on": [datetime.now().isoformat()],
                "Technology": [tech],
                "Program": [program],
                "Gate_DeltaPmp_%": [gate_.get("Delta_Pmp_%") if gate_ else None]
            })
            summary.to_excel(writer, index=False, sheet_name="Summary")
            if notes_:
                pd.DataFrame({"Notes": notes_}).to_excel(writer, index=False, sheet_name="Notes")
        return output.getvalue()

    xlsx = to_excel_bytes(df, notes, gate_results if gate_results else {})
    st.download_button("Download Excel (.xlsx)", data=xlsx, file_name="IEC62915_Retest_Plan.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.download_button("Download CSV (.csv)", data=df.to_csv(index=False).encode("utf-8"), file_name="IEC62915_Retest_Plan.csv", mime="text/csv")

    snapshot = {
        "generated_on": datetime.now().isoformat(),
        "technology": tech,
        "program": program,
        "sequences": list(sorted(seq_flags)),
        "gate": gate_results,
        "mods": mods,
        "inputs": params,
        "plan": tests,
        "notes": notes
    }
    st.download_button("Download JSON snapshot", data=json.dumps(snapshot, indent=2).encode("utf-8"), file_name="IEC62915_Retest_Snapshot.json", mime="application/json")
