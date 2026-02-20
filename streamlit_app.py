import json
from io import BytesIO
from datetime import datetime
import pandas as pd
import streamlit as st

# ============================================================
# IEC 62915:2023 Retesting Planner (Decision Support) — with BOM Import
# Implements modification-driven retest logic per IEC TS 62915:2023 (Edition 2.0, 2023-09)
# Baseline, Gate-1/Gate-2, and sequence notions per Clause 4.1; WBT/MLI per 4.2/4.3; flow context per Annex A.
# NOTE: This tool supports decision-making; final programs must be validated by qualified engineers.
# ============================================================

st.set_page_config(page_title="IEC 62915:2023 – Retesting Planner", layout="wide")

# -----------------------
# Dictionaries (tests and sequence labels)
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
    "MST 57": "Insulation coordination evaluation (61730-1 reference)"
}

SEQUENCE_FLAGS = {
    "SEQ_B": "61730 Sequence B (polymeric outer / adhesive/label cases etc.)",
    "SEQ_B1": "61730 Sequence B1 (pollution degree 1 variants)"
}

# -----------------------
# Utility helpers
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
# Rule engine (same as before, abridged here for brevity in comments)
# Each rule function references IEC TS 62915:2023 clause(s).
# -----------------------

def rules_frontsheet(p, tech, include_61215, include_61730, seq_flags, plan):
    glass = p.get("material_type") == "glass"
    non_glass = not glass
    thickness_change = p.get("thickness_change_pct") or 0.0
    surface_change = p.get("surface_treatment_changed", False)
    ar_cmp = p.get("ar_lambda_c_uv_change", "unknown")
    strengthen_change = p.get("strengthening_change", False)
    model_designation_change = p.get("model_designation_change", False)
    glass_to_from_nonglass = p.get("glass_to_poly_or_vice_versa", False)

    if glass_to_from_nonglass:
        add_note(plan, "Frontsheet change between glass and non-glass suggests full qualification (TS 4.2.1/4.3.1).")

    # IEC 61215
    if include_61215:
        if glass and (strengthen_change or thickness_change < 0):
            add_test(plan, "IEC 61215", "MQT 09", "Frontsheet: glass strength/thickness change", "4.2.1/4.3.1")
        if non_glass and (model_designation_change or thickness_change < 0):
            add_test(plan, "IEC 61215", "MQT 09", "Frontsheet non-glass model/thickness change", "4.2.1/4.3.1")

        if not (glass and ar_cmp == ">= previous"):
            add_test(plan, "IEC 61215", "MQT 10", "UV preconditioning for frontsheet change", "4.2.1/4.3.1")
            add_test(plan, "IEC 61215", "MQT 20", "Cyclic (dynamic) mechanical load", "4.2.1/4.3.1")
            add_test(plan, "IEC 61215", "MQT 11-50", "Thermal cycling 50 cycles", "4.2.1/4.3.1")
            add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.1/4.3.1")
            if p.get("jb_on_frontsheet", False):
                add_test(plan, "IEC 61215", "MQT 14.1", "Retention of J-box on frontsheet", "4.2.1/4.3.1")

        if non_glass or surface_change:
            add_test(plan, "IEC 61215", "MQT 13", "Damp heat for frontsheet change", "4.2.1/4.3.1")

        if p.get("flexible_module", False) and non_glass:
            add_test(plan, "IEC 61215", "MQT 22", "Bending test for flexible non-glass", "4.2.1/4.3.1")

        if not (surface_change and p.get("outside_surface_only", False)):
            add_test(plan, "IEC 61215", "MQT 16", "Static mechanical load (frontsheet)", "4.2.1/4.3.1")
            add_test(plan, "IEC 61215", "MQT 17", "Hail test (frontsheet change)", "4.2.1/4.3.1")

    # IEC 61730
    if include_61730:
        if not (glass and ar_cmp == ">= previous"):
            add_test(plan, "IEC 61730", "MST 54", "UV test for frontsheet change", "4.2.1/4.3.1")
            add_test(plan, "IEC 61730", "MST 51-50", "Thermal cycling 50 cycles", "4.2.1/4.3.1")
            add_test(plan, "IEC 61730", "MST 52", "Humidity freeze", "4.2.1/4.3.1")
            if p.get("jb_on_frontsheet", False):
                add_test(plan, "IEC 61730", "MST 42", "Robustness of terminations (frontsheet J-box)", "4.2.1/4.3.1")

        if non_glass or surface_change:
            add_test(plan, "IEC 61730", "MST 53", "Damp heat for frontsheet change", "4.2.1/4.3.1")

        if not (surface_change and p.get("outside_surface_only", False)):
            add_test(plan, "IEC 61730", "MST 34", "Static mechanical load (frontsheet)", "4.2.1/4.3.1")

        if non_glass:
            add_test(plan, "IEC 61730", "MST 04", "Insulation thickness test (non-glass)", "4.2.1/4.3.1")
            add_test(plan, "IEC 61730", "MST 12", "Cut susceptibility (non-glass)", "4.2.1/4.3.1")
            if model_designation_change or thickness_change < 0:
                add_test(plan, "IEC 61730", "MST 14", "Impulse voltage (non-glass changed/reduced)", "4.2.1/4.3.1")
            add_test(plan, "IEC 61730", "MST 24", "Ignitability (non-glass)", "4.2.1/4.3.1")
            add_sequence_flag(seq_flags, "SEQ_B", "4.2.1/4.3.1")

        if glass and not (surface_change and p.get("outside_surface_only", False)):
            add_test(plan, "IEC 61730", "MST 32", "Module breakage (glass)", "4.2.1/4.3.1")

        if p.get("cemented_joint", False):
            add_test(plan, "IEC 61730", "MST 35", "Peel test (cemented joint)", "4.2.1/4.3.1")
            add_test(plan, "IEC 61730", "MST 36", "Lap shear (cemented joint)", "4.2.1/4.3.1")


def rules_encapsulation(p, tech, include_61215, include_61730, seq_flags, plan):
    diff_mat = p.get("different_material", False)
    add_change = p.get("additives_change_same_material", False)
    thickness_change = p.get("thickness_change_pct") or 0.0
    flexible = p.get("flexible_module", False)
    rho_drop_order = p.get("volume_resistivity_drop_order", 0)

    if include_61215:
        add_test(plan, "IEC 61215", "MQT 09", "Encapsulation change", "4.2.2/4.3.2")
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


def rules_cell_technology_wbt(p, include_61215, include_61730, plan):
    if include_61215:
        add_test(plan, "IEC 61215", "MQT 20", "Dyn mech load (cell tech change)", "4.2.3")
        add_test(plan, "IEC 61215", "MQT 11-50", "Thermal cycling 50", "4.2.3")
        add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.3")
        if any([p.get("tech_change"), p.get("ar_change"), p.get("crystallization_change"), p.get("manufacturer_change")]):
            add_test(plan, "IEC 61215", "MQT 21", "PID (cell technology/AR/crystallization/manufacturer change)", "4.2.3")
        add_test(plan, "IEC 61215", "MQT 09", "Hot-spot endurance (cell tech change)", "4.2.3")
        add_test(plan, "IEC 61215", "MQT 11-200", "Thermal cycling 200", "4.2.3")
        add_test(plan, "IEC 61215", "MQT 13", "Damp heat (cell tech change)", "4.2.3")
        if p.get("cell_thickness_reduction_pct", 0) < 0 or p.get("crystallization_change"):
            add_test(plan, "IEC 61215", "MQT 16", "Static mechanical load (thickness/crystallization)", "4.2.3")
        if p.get("cell_thickness_reduction_pct", 0) < 0:
            add_test(plan, "IEC 61215", "MQT 17", "Hail (reduced cell thickness)", "4.2.3")
    if include_61730:
        add_test(plan, "IEC 61730", "MST 22", "Hot-spot endurance (cell tech)", "4.2.3")
        add_test(plan, "IEC 61730", "MST 51-200", "Thermal cycling 200", "4.2.3")
        add_test(plan, "IEC 61730", "MST 53", "Damp heat (cell tech)", "4.2.3")
        if p.get("cell_thickness_reduction_pct", 0) < 0 or p.get("crystallization_change"):
            add_test(plan, "IEC 61730", "MST 34", "Static mechanical load (thickness/crystallization)", "4.2.3")
        if not p.get("crystallization_change", False):
            add_test(plan, "IEC 61730", "MST 26", "Reverse current overload (cell tech)", "4.2.3")


def rules_interconnect_wbt(p, include_61215, include_61730, plan):
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


def rules_backsheet(p, tech, include_61215, include_61730, seq_flags, plan):
    glass = p.get("material_type") == "glass"
    non_glass = not glass
    thickness_change = p.get("thickness_change_pct") or 0.0
    surface_change = p.get("surface_treatment_changed", False)
    outside_only = p.get("outside_surface_only", False)

    if include_61215:
        add_test(plan, "IEC 61215", "MQT 10", "UV preconditioning", "4.2.5/4.3.9")
        add_test(plan, "IEC 61215", "MQT 20", "Cyclic (dynamic) mechanical load", "4.2.5/4.3.9")
        add_test(plan, "IEC 61215", "MQT 11-50", "Thermal cycling 50", "4.2.5/4.3.9")
        add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze", "4.2.5/4.3.9")
        if p.get("jb_on_backsheet", False):
            add_test(plan, "IEC 61215", "MQT 14.1", "Retention of J-box on mounting surface", "4.2.5/4.3.9")
        if non_glass or surface_change:
            add_test(plan, "IEC 61215", "MQT 13", "Damp heat (backsheet)", "4.2.5/4.3.9")
        if p.get("flexible_module", False) and non_glass:
            add_test(plan, "IEC 61215", "MQT 22", "Bending test (flexible)", "4.2.5/4.3.9")
        if glass or p.get("mounting_depends_on_backsheet", False):
            add_test(plan, "IEC 61215", "MQT 16", "Static mechanical load (backsheet)", "4.2.5/4.3.9")
        if p.get("rigidity_depends_on_backsheet", False):
            add_test(plan, "IEC 61215", "MQT 17", "Hail (rigidity depends on backsheet)", "4.2.5/4.3.9")
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


def rules_electrical_termination(p, include_61215, include_61730, seq_flags, plan):
    if include_61215:
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


def rules_bypass_diode(p, include_61215, include_61730, plan):
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


def rules_electrical_circuitry_wbt(p, include_61215, include_61730, plan):
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


def rules_edge_seal(p, include_61215, include_61730, seq_flags, plan):
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


def rules_frame_mounting(p, include_61215, include_61730, plan):
    if include_61215:
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


def rules_module_size(p, tech, include_61215, include_61730, plan):
    inc = p.get("increase_pct", 0.0)
    if inc > 20.0:
        if include_61215:
            add_test(plan, "IEC 61215", "MQT 11-200", "Thermal cycling 200 (size increase >20%)", "4.2.11/4.3.14")
            add_test(plan, "IEC 61215", "MQT 13", "Damp heat (size increase)", "4.2.11/4.3.14")
            add_test(plan, "IEC 61215", "MQT 16", "Static mechanical load (size increase)", "4.2.11/4.3.14")
            if p.get("non_tempered_or_nonglass", False):
                add_test(plan, "IEC 61215", "MQT 17", "Hail (non-tempered or non-glass)", "4.2.11/4.3.14")
            if p.get("flexible_module", False):
                add_test(plan, "IEC 61215", "MQT 22", "Bending (flexible)", "4.2.11/4.3.14")
        if include_61730:
            add_test(plan, "IEC 61730", "MST 51-200", "Thermal cycling 200 (size increase >20%)", "4.2.11/4.3.14")
            add_test(plan, "IEC 61730", "MST 53", "Damp heat (size increase)", "4.2.11/4.3.14")
            add_test(plan, "IEC 61730", "MST 34", "Static mechanical load (size increase)", "4.2.11/4.3.14")
            add_test(plan, "IEC 61730", "MST 32", "Module breakage (size increase)", "4.2.11/4.3.14")


def rules_output_power_identical_size(p, include_61215, include_61730, plan):
    if include_61215:
        add_test(plan, "IEC 61215", "MQT 09", "Hot-spot (power change, identical size)", "4.2.12/4.3.15")
        if p.get("isc_increase_pct", 0.0) > 10.0:
            add_test(plan, "IEC 61215", "MQT 11-200", "Thermal cycling 200 (Isc increase >10%)", "4.2.12/4.3.15")
            add_test(plan, "IEC 61215", "MQT 18", "Bypass diode thermal (Isc increase >10%)", "4.2.12/4.3.15")
    if include_61730:
        add_test(plan, "IEC 61730", "MST 22", "Hot-spot (power change)", "4.2.12/4.3.15")
        if p.get("isc_increase_pct", 0.0) > 10.0:
            add_test(plan, "IEC 61730", "MST 51-200", "Thermal cycling 200 (Isc increase >10%)", "4.2.12/4.3.15")
            add_test(plan, "IEC 61730", "MST 25", "Bypass diode thermal (Isc increase >10%)", "4.2.12/4.3.15")
        add_test(plan, "IEC 61730", "MST 26", "Reverse current overload", "4.2.12/4.3.15")


def rules_ocp_increase(p, include_61730, plan):
    if include_61730 and p.get("ocp_increased", False):
        add_test(plan, "IEC 61730", "MST 13", "Continuity of equipotential bonding (OCP increase)", "4.2.13/4.3.16")
        add_test(plan, "IEC 61730", "MST 26", "Reverse current overload (OCP increase)", "4.2.13/4.3.16")


def rules_system_voltage_increase(p, include_61215, include_61730, seq_flags, plan):
    if not p.get("increased_by_gt5", False):
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
        if p.get("non_glass_outer", False):
            add_test(plan, "IEC 61730", "MST 12", "Cut susceptibility (non-glass)", "4.2.14/4.3.17")
        add_test(plan, "IEC 61730", "MST 13", "Continuity of equipotential bonding", "4.2.14/4.3.17")
        add_test(plan, "IEC 61730", "MST 14", "Impulse voltage", "4.2.14/4.3.17")
        add_sequence_flag(seq_flags, "SEQ_B", "4.2.14/4.3.17")


def rules_cell_fixing_internal_tape_wbt(p, include_61215, plan):
    if include_61215 and p.get("diff_material_or_manufacturer", False):
        add_test(plan, "IEC 61215", "MQT 12", "Humidity freeze (cell fixing/internal tape)", "4.2.15")


def rules_label_material(p, include_61730, seq_flags, plan):
    if include_61730 and p.get("diff_label_or_ink_or_adhesive", False):
        add_test(plan, "IEC 61730", "MST 05", "Durability of markings", "4.2.16/4.3.18")
        add_sequence_flag(seq_flags, "SEQ_B", "4.2.16/4.3.18")


def rules_monofacial_to_bifacial(p, include_61215, include_61730, plan):
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


def rules_operating_temperature(p, plan):
    if p.get("qualifying_to_level", "none") in ("level1", "level2"):
        add_note(plan, "Re-run sequences at modified temperatures per IEC TS 63126 for high-temperature operation. (4.2.18/4.3.20)")

def rules_mli_front_back_contact_edge_deletion_interconnect(p, include_61215, include_61730, plan):
    if p.get("mli_front_contact_change", False):
        if include_61215:
            for t in ["MQT 09","MQT 10","MQT 20","MQT 11-50","MQT 12","MQT 13"]:
                add_test(plan, "IEC 61215", t, "MLI front contact change", "4.3.3")
        if include_61730:
            for t in ["MST 22","MST 54","MST 51-50","MST 52","MST 53","MST 14","MST 26"]:
                add_test(plan, "IEC 61730", t, "MLI front contact change", "4.3.3")
    if p.get("mli_back_contact_change", False):
        if include_61215:
            for t in ["MQT 09","MQT 20","MQT 11-50","MQT 12","MQT 13"]:
                add_test(plan, "IEC 61215", t, "MLI back contact change", "4.3.6")
        if include_61730:
            for t in ["MST 22","MST 51-50","MST 52","MST 53","MST 14","MST 26"]:
                add_test(plan, "IEC 61730", t, "MLI back contact change", "4.3.6")
    if p.get("mli_edge_deletion_change", False):
        if include_61215:
            for t in ["MQT 20","MQT 11-50","MQT 12","MQT 13"]:
                add_test(plan, "IEC 61215", t, "MLI edge deletion change", "4.3.7")
        if include_61730:
            for t in ["MST 51-50","MST 52","MST 53","MST 14"]:
                add_test(plan, "IEC 61730", t, "MLI edge deletion change", "4.3.7")
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
# Shared planner used by UI AND importer
# -----------------------

def build_plan(tech, program, mods, params, gate_input=None):
    include_61215 = program in ("IEC 61215 only", "Combined IEC 61215 + IEC 61730", "61215", "Combined")
    include_61730 = program in ("IEC 61730 only", "Combined IEC 61215 + IEC 61730", "61730", "Combined")

    plan = {}
    seq_flags = set()

    # Baseline
    baseline_checks(include_61215, include_61730, plan)

    # Gate (record only)
    if gate_input and include_61215:
        rated = gate_input.get("rated_Pmp_W", 0.0)
        meas = gate_input.get("measured_Pmp_W", 0.0)
        delta = (meas - rated) / rated * 100.0 if rated > 0 else None
        add_note(plan, f"Gate-1/2 recorded: ΔPmp%={delta:.2f}% (engineer to assess per IEC 61215-1).")

    # Apply rules
    def _p(prefix, key, default=None):
        return params.get(f"{prefix}.{key}", default)

    if "Frontsheet" in mods:
        rules_frontsheet(
            {
                "material_type": _p("frontsheet","material_type"),
                "thickness_change_pct": _p("frontsheet","thickness_change_pct"),
                "surface_treatment_changed": _p("frontsheet","surface_treatment_changed"),
                "outside_surface_only": _p("frontsheet","outside_surface_only"),
                "ar_lambda_c_uv_change": _p("frontsheet","ar_lambda_c_uv_change","unknown"),
                "strengthening_change": _p("frontsheet","strengthening_change"),
                "jb_on_frontsheet": _p("frontsheet","jb_on_frontsheet"),
                "flexible_module": _p("frontsheet","flexible_module"),
                "cemented_joint": _p("frontsheet","cemented_joint"),
                "model_designation_change": _p("frontsheet","model_designation_change"),
                "glass_to_poly_or_vice_versa": _p("frontsheet","glass_to_poly_or_vice_versa"),
            },
            tech, include_61215, include_61730, seq_flags, plan
        )

    if "Encapsulation" in mods:
        rules_encapsulation(
            {
                "different_material": _p("encap","different_material"),
                "additives_change_same_material": _p("encap","additives_change_same_material"),
                "thickness_change_pct": _p("encap","thickness_change_pct"),
                "flexible_module": _p("encap","flexible_module"),
                "frontsheet_polymeric": _p("encap","frontsheet_polymeric"),
                "front_or_back_polymeric": _p("encap","front_or_back_polymeric", True),
                "volume_resistivity_drop_order": _p("encap","volume_resistivity_drop_order", 0),
                "material_changed_composition": _p("encap","material_changed_composition"),
                "cemented_joint": _p("encap","cemented_joint"),
                "pollution_degree_1": _p("encap","pollution_degree_1"),
            },
            tech, include_61215, include_61730, seq_flags, plan
        )

    if "Cell technology (WBT)" in mods and tech.startswith("WBT"):
        rules_cell_technology_wbt(
            {
                "tech_change": _p("cell","tech_change"),
                "ar_change": _p("cell","ar_change"),
                "crystallization_change": _p("cell","crystallization_change"),
                "manufacturer_change": _p("cell","manufacturer_change"),
                "cell_thickness_reduction_pct": _p("cell","cell_thickness_reduction_pct", 0),
                "cell_size_change_pct": _p("cell","cell_size_change_pct", 0),
                "moved_to_half_cell": _p("cell","moved_to_half_cell"),
            },
            include_61215, include_61730, plan
        )

    if "Cell & string interconnect (WBT)" in mods and tech.startswith("WBT"):
        rules_interconnect_wbt(
            {
                "different_material": _p("ic","different_material"),
                "solder_flux_change": _p("ic","solder_flux_change"),
                "bonding_tech_change": _p("ic","bonding_tech_change"),
                "cross_section_change_pct": _p("ic","cross_section_change_pct", 0),
            },
            include_61215, include_61730, plan
        )

    if "Backsheet" in mods:
        rules_backsheet(
            {
                "material_type": _p("backsheet","material_type"),
                "thickness_change_pct": _p("backsheet","thickness_change_pct"),
                "surface_treatment_changed": _p("backsheet","surface_treatment_changed"),
                "outside_surface_only": _p("backsheet","outside_surface_only"),
                "jb_on_backsheet": _p("backsheet","jb_on_backsheet"),
                "flexible_module": _p("backsheet","flexible_module"),
                "rigidity_depends_on_backsheet": _p("backsheet","rigidity_depends_on_backsheet"),
                "mounting_depends_on_backsheet": _p("backsheet","mounting_depends_on_backsheet"),
                "cemented_joint": _p("backsheet","cemented_joint"),
                "model_designation_change": _p("backsheet","model_designation_change"),
                "pollution_degree_1": _p("backsheet","pollution_degree_1"),
                "strengthening_change": _p("backsheet","strengthening_change"),
            },
            tech, include_61215, include_61730, seq_flags, plan
        )

    if "Electrical termination" in mods:
        rules_electrical_termination(
            {
                "potting_change_only": _p("term","potting_change_only"),
                "only_cable_or_connector_change": _p("term","only_cable_or_connector_change"),
                "only_mech_attachment_or_num_jb": _p("term","only_mech_attachment_or_num_jb"),
                "jb_prequalified": _p("term","jb_prequalified"),
                "jb_not_sun_exposed": _p("term","jb_not_sun_exposed"),
                "electrical_attachment_change": _p("term","electrical_attachment_change"),
                "adhesive_change": _p("term","adhesive_change"),
                "screw_connections_applicable": _p("term","screw_connections_applicable"),
                "cemented_joint": _p("term","cemented_joint"),
                "relocation_or_position_only": _p("term","relocation_or_position_only"),
                "jb_weight_increase": _p("term","jb_weight_increase"),
                "pollution_degree_1": _p("term","pollution_degree_1"),
            },
            include_61215, include_61730, seq_flags, plan
        )

    if "Bypass diode" in mods:
        rules_bypass_diode(
            {
                "cells_per_diode_changed": _p("diode","cells_per_diode_changed"),
                "mounting_method_change": _p("diode","mounting_method_change"),
            },
            include_61215, include_61730, plan
        )

    if "Electrical circuitry (WBT)" in mods and tech.startswith("WBT"):
        rules_electrical_circuitry_wbt(
            {
                "more_cells_per_diode": _p("circ","more_cells_per_diode"),
                "internal_conductors_behind_cells": _p("circ","internal_conductors_behind_cells"),
                "isc_increase_pct": _p("circ","isc_increase_pct", 0.0),
                "reroute_output_leads": _p("circ","reroute_output_leads"),
                "polymeric_outer": _p("circ","polymeric_outer"),
                "operating_v_or_i_increase_pct": _p("circ","operating_v_or_i_increase_pct", 0.0),
            },
            include_61215, include_61730, plan
        )

    if "Edge sealing" in mods:
        rules_edge_seal(
            {
                "diff_material": _p("edge","diff_material"),
                "thickness_or_width_change": _p("edge","thickness_or_width_change"),
                "outer_enclosure": _p("edge","outer_enclosure"),
            },
            include_61215, include_61730, seq_flags, plan
        )

    if "Frame & mounting" in mods:
        rules_frame_mounting(
            {
                "adhesive_change": _p("frame","adhesive_change"),
                "polymeric_frame_change": _p("frame","polymeric_frame_change"),
                "framed_to_frameless": _p("frame","framed_to_frameless"),
                "equipotential_bonding_change": _p("frame","equipotential_bonding_change"),
                "screw_connections_applicable": _p("frame","screw_connections_applicable"),
                "creep_not_prevented_anymore": _p("frame","creep_not_prevented_anymore"),
                "nonpolymeric_to_polymeric": _p("frame","nonpolymeric_to_polymeric"),
                "mounting_method_change": _p("frame","mounting_method_change"),
            },
            include_61215, include_61730, plan
        )

    if "Module size increase" in mods:
        rules_module_size(
            {
                "increase_pct": _p("size","increase_pct", 0.0),
                "non_tempered_or_nonglass": _p("size","non_tempered_or_nonglass", False),
                "flexible_module": _p("size","flexible_module", False)
            },
            tech, include_61215, include_61730, plan
        )

    if "Higher/lower output power (identical design & size)" in mods:
        rules_output_power_identical_size(
            {
                "delta_power_pct": _p("pwr","delta_power_pct", 0.0),
                "isc_increase_pct": _p("pwr","isc_increase_pct", 0.0),
            },
            include_61215, include_61730, plan
        )

    if "Increase OCP rating" in mods:
        rules_ocp_increase({"ocp_increased": _p("ocp","ocp_increased", False)}, include_61730, plan)

    if "Increase system voltage (>5%)" in mods:
        rules_system_voltage_increase(
            {
                "increased_by_gt5": _p("vsys","increased_by_gt5", False),
                "non_glass_outer": _p("vsys","non_glass_outer", False),
            },
            include_61215, include_61730, seq_flags, plan
        )

    if "Cell fixing / internal insulation tape (WBT)" in mods and tech.startswith("WBT"):
        rules_cell_fixing_internal_tape_wbt(
            {"diff_material_or_manufacturer": _p("tape","diff_material_or_manufacturer", False)},
            include_61215, plan
        )

    if "Label material (external nameplate)" in mods:
        rules_label_material(
            {
                "diff_label_or_ink_or_adhesive": _p("label","diff_label_or_ink_or_adhesive", False),
                "side_has_label_exposed_to_uv": _p("label","side_has_label_exposed_to_uv", False),
                "coupon_ok": _p("label","coupon_ok", False),
            },
            include_61730, seq_flags, plan
        )

    if "Change to bifacial" in mods:
        rules_monofacial_to_bifacial(
            {
                "include_tc50_block": _p("bif","include_tc50_block", True),
                "glass_backsheet": _p("bif","glass_backsheet", False),
            },
            include_61215, include_61730, plan
        )

    if "Operating temperature category increase (TS 63126)" in mods:
        rules_operating_temperature(
            {"qualifying_to_level": _p("temp","qualifying_to_level", "none")},
            plan
        )

    # Collect tests dataframe
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
    return df, notes, seq_flags

# -----------------------
# UI — Tabs: Interactive | BOM Import | Help
# -----------------------

tabs = st.tabs(["Interactive Planner", "BOM Import (Excel/CSV)", "Help & Template"])

# ========== Tab 1: Interactive Planner ==========
with tabs[0]:
    st.title("IEC TS 62915:2023 — Retesting Planner (Decision Support)")
    st.caption("Encodes key decision logic from IEC TS 62915:2023. Final review by qualified engineers is required.")

    # Quick profiles
    with st.expander("Quick Profiles"):
        prof = st.selectbox("Select a profile", ["None", "HJT glass/glass bifacial (WBT, Combined)", "TOPCon glass/backsheet (WBT, Combined)"])
        if st.button("Apply Profile"):
            if prof != "None":
                st.session_state["tech"] = "WBT (wafer-based)"
