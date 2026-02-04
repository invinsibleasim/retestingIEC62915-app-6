# streamlit_app.py
# IEC TS 62915:2023 Retesting Planner (indicative, customizable)
# Author: Asim's Copilot
# Notes:
# - This app provides an engineering-judgment *starting point* for retesting planning.
# - Final test sequences & sample counts MUST be taken from the official IEC matrix and
#   the invoked base standards: IEC 61215:2021 (design qualification) and IEC 61730:2023 (safety).
# - 62915:2023 adds clarity for new tests (e.g., MQT 20 dynamic mechanical load; MQT 21 PID),
#   separates 61215 vs 61730 retest requirements, and references IEC 62941 QMS and IEC 62788 component series.
# - Corrigendum 1 (2024) updates the "electrical termination" subclause language and points back to
#   IEC 61730-2 Clause 6 and IEC 61215-1 Clause 4 for module/component testing.

import re
from io import BytesIO

import pandas as pd
import streamlit as st

st.set_page_config(page_title="IEC TS 62915:2023 Retesting Planner", layout="wide")

# -----------------------------
# Reference: MQT test dictionary (descriptions are brief & generic for planning)
# -----------------------------
MQT_INFO = {
    "MQT 01": "Visual inspection",
    "MQT 02": "Maximum power determination (STC) / Performance check",
    "MQT 03": "Insulation test",
    "MQT 04": "Measurement of temperature coefficients",
    "MQT 06.1": "Performance at STC",
    "MQT 07": "Performance at low irradiance",
    "MQT 08": "Outdoor exposure test",
    "MQT 09": "Hot-spot endurance test",
    "MQT 10": "UV preconditioning",
    "MQT 11": "Thermal cycling test (e.g., TC50/TC200)",
    "MQT 12": "Humidity freeze test (e.g., HF10)",
    "MQT 13": "Damp heat (e.g., DH1000)",
    "MQT 14": "Robustness of termination (ROT)",
    "MQT 14.1": "Retention of junction box on mounting surface (ROT)",
    "MQT 14.2": "Cord anchorage (ROT)",
    "MQT 15": "Wet leakage current test",
    "MQT 16": "Static mechanical load test",
    "MQT 17": "Hail test",
    "MQT 18": "Bypass diode thermal test",
    "MQT 19": "Stabilization",
    "MQT 20": "Cyclic (dynamic) mechanical load",
    "MQT 21": "Potential-induced degradation (PID)",
    "MQT 22": "Bending test",
}

# -----------------------------
# Reference: IEC 61730 (Safety) - test descriptions (selected)
# -----------------------------
MST_INFO = {
    "MST 01": "Visual inspection",
    "MST 02": "Performance at STC",
    "MST 03": "Maximum power determination",
    "MST 04": "Insulation thickness",
    "MST 05": "Durability of markings",
    "MST 06": "Sharp edge test",
    "MST 07": "Bypass diode functionality test",
    "MST 11": "Accessibility test",
    "MST 12": "Cut susceptibility test",
    "MST 13": "Continuity test for equipotential bonding",
    "MST 14": "Impulse voltage test",
    "MST 16": "Insulation test",
    "MST 17": "Wet leakage current test",
    "MST 22": "Hot-spot endurance test",
    "MST 23": "Fire test",
    "MST 24": "Ignitability test",
    "MST 25": "Bypass diode thermal test",
    "MST 26": "Reverse current overload test (RCOT)",
    "MST 32": "Module breakage test (MBT)",
    "MST 33": "Screw connection test",
    "MST 34": "Static mechanical load test",
    "MST 35": "Peel test",
    "MST 36": "Lap shear strength test",
    "MST 37": "Materials creep test",
    "MST 42": "Robustness of terminations (maps to MQT 14)",
    "MST 51": "Thermal cycling (TC50/TC200)",
    "MST 52": "Humidity freeze (HF10)",
    "MST 53": "Damp heat (DH200/DH1000)",
    "MST 54": "UV preconditioning",
    "MST 55": "Cold conditioning",
    "MST 56": "Dry heat conditioning",
    "MST 57": "Evaluation of insulation coordination",
}

# Merge to a single description map for convenience
DESCR_MAP = {**MQT_INFO, **MST_INFO}

def describe_label(label: str) -> str:
    """
    Extract 'MQT xx[.x]' or 'MST xx[.x]' code from a label like 'TC50 (MQT 11)' or 'RCOT (MST 26)'
    and return a human-readable description; else return ''.
    """
    if not isinstance(label, str):
        return ""
    # Normalize HTML entities if any were pasted in
    s = label.replace("&amp;", "&")
    m = re.search(r"\b(MQT|MST)\s*\d+(\.\d+)?\b", s, flags=re.IGNORECASE)
    if m:
        code = f"{m.group(1).upper()} {m.group(0).split()[-1]}"
        return DESCR_MAP.get(code, "")
    return ""

# -----------------------------
# Indicative retest matrix for Wafer-Based Technology (WBT) modules
# (Engineering judgment placeholders – align with the official 62915 matrix before use)
# -----------------------------
WBT_MATRIX = {
    "Frontsheet change": {
        "IEC 61215": [
            "Hot-spot endurance test (MQT 09)",
            "UV15 (MQT 10)",
            "DMLT (MQT 20)",
            "TC50 (MQT 11)",
            "HF10 (MQT 12)",
            "ROT (MQT 14.1)",
            "DH1000 (MQT 13)",
            "Bending test (MQT 22) for Flexible module",
            "SMLT (MQT 16)",
            "Hail (MQT 17)",
        ],
        "IEC 61730": [
            "Insulation thickness (MST 04) if non-glass",
            "Cut susceptibility (MST 12) if non-glass",
            "Impulse voltage test (MST 14)",
            "Ignitability test (MST 24) if non-glass",
            "Module breakage test (MST 32)",
            "Peel/Lap (MST 35/36) for cemented joints / thickness change",
            "Materials creep (MST 37)",
            "Sequence B if non-glass",
            "Sequence B1 if PD1",
        ],
    },
    "Encapsulant (EVA/POE) change or stack change": {
        "IEC 61215": [
            "Hot-spot endurance test (MQT 09)",
            "UV15 (MQT 10)",
            "DMLT (MQT 20)",
            "TC50 (MQT 11)",
            "HF10 (MQT 12)",
            "TC200 (MQT 11)",
            "DH1000 (MQT 13)",
            "Bending test (MQT 22) for Flexible module",
            "PID (MQT 21)",
            "Hail (MQT 17)",
        ],
        "IEC 61730": [
            "Cut susceptibility (MST 12) if non-glass",
            "Impulse voltage test (MST 14)",
            "Module breakage test (MST 32)",
            "Peel/Lap (MST 35/36) for cemented joints",
            "Materials creep (MST 37)",
            "Sequence B",
            "Sequence B1 if PD1",
        ],
    },
    "Cell technology change (e.g., PERC → TOPCon/HJT)": {
        "IEC 61215": [
            "Hot-spot endurance test (MQT 09)",
            "DMLT (MQT 20)",
            "TC50 (MQT 11)",
            "HF10 (MQT 12)",
            "TC200 (MQT 11)",
            "DH1000 (MQT 13)",
            "Bending test (MQT 22) for Flexible module",
            "PID (MQT 21)",
            "SMLT (MQT 16)",
            "Hail (MQT 17)",
        ],
        "IEC 61730": ["RCOT (MST 26)"],
    },
    "Interconnect/ribbon/paste change": {
        "IEC 61215": [
            "Hot-spot endurance test (MQT 09)",
            "TC200 (MQT 11)",
            "DH1000 (MQT 13)",
        ],
        "IEC 61730": ["RCOT (MST 26)"],
    },
    "Backsheet change": {
        "IEC 61215": [
            "Hot-spot endurance test (MQT 09)",
            "UV15 (MQT 10)",
            "DMLT (MQT 20)",
            "TC50 (MQT 11)",
            "HF10 (MQT 12)",
            "ROT (MQT 14.1)",
            "DH1000 (MQT 13)",
            "Bending test (MQT 22) for Flexible module",
            "SMLT (MQT 16)",
            "Hail (MQT 17)",
        ],
        "IEC 61730": [
            "Insulation thickness (MST 04) if non-glass",
            "Cut susceptibility (MST 12) if non-glass",
            "Impulse voltage test (MST 14)",
            "Ignitability test (MST 24) if non-glass",
            "Module breakage test (MST 32)",
            "Peel/Lap (MST 35/36) for cemented joints / thickness change",
            "Materials creep (MST 37)",
            "Sequence B if non-glass",
            "Sequence B1 if PD1",
        ],
    },
    "Electrical termination (J-box/cable/connector) change": {
        "IEC 61215": [
            "UV15 (MQT 10)",
            "DMLT (MQT 20)",
            "TC50 (MQT 11)",
            "HF10 (MQT 12)",
            "ROT (MQT 14.1)",
            "ROT (MQT 14.2)",
            "DH1000 (MQT 13)",
            "BPDT (MQT 18)",
        ],
        "IEC 61730": [
            "Insulation thickness (MST 04) if non-glass",
            "Cut susceptibility (MST 12) if non-glass",
            "Impulse voltage test (MST 14)",
            "Ignitability test (MST 24) if non-glass",
            "Module breakage test (MST 32)",
            "Peel/Lap (MST 35/36) for cemented joints / thickness change",
            "Materials creep (MST 37)",
            "Sequence B if non-glass",
            "Sequence B1 if PD1",
        ],
    },
    "Bypass diode change": {
        "IEC 61215": ["Hot-spot endurance test (MQT 09)", "TC200 (MQT 11)", "BPDT (MQT 18)"],
        "IEC 61730": ["RCOT (MST 26)"],
    },
    "Electrical circuitry change": {
        "IEC 61215": ["Hot-spot endurance test (MQT 09)", "TC200 (MQT 11)", "BPDT (MQT 18)"],
        "IEC 61730": [
            "Cut susceptibility (MST 12) for rerouting of output leads (polymeric backsheet or frontsheet)",
            "Insulation thickness (MST 04) for rerouting of output leads (polymeric backsheet or frontsheet)",
            "RCOT (MST 26)",
        ],
    },
    "Edge seal change": {
        "IEC 61215": ["UV15 (MQT 10)", "DMLT (MQT 20)", "TC50 (MQT 11)", "HF10 (MQT 12)", "DH1000 (MQT 13)"],
        "IEC 61730": [
            "Impulse voltage test (MST 14)",
            "Ignitability test (MST 24) only if edge sealing is accessible",
            "Peel/Lap (MST 35/36) for cemented joints / thickness change",
            "Sequence B (not for different thickness or width)",
            "Sequence B1 if PD1",
        ],
    },
    "Frame/mounting redesign": {
        "IEC 61215": ["UV15 (MQT 10)", "DMLT (MQT 20)", "TC50 (MQT 11)", "HF10 (MQT 12)", "DH1000 (MQT 13) for polymeric frame", "SMLT (MQT 16)", "Hail (MQT 17)"],
        "IEC 61730": [
            "Continuity test of equipotential bonding (MST 13)",
            "Ignitability test (MST 24) for polymeric frame",
            "Module breakage test (MST 32)",
            "Screw connection (MST 33) if applicable",
            "Sequence B (not for polymeric frames)",
        ],
    },
    "Module size change": {
        "IEC 61215": ["TC200 (MQT 11)", "DH1000 (MQT 13)", "SMLT (MQT 16)", "Hail (MQT 17)", "Bending test (MQT 22) for Flexible module"],
        "IEC 61730": ["RCOT (MST 26)", "Module breakage test (MST 32)"],
    },
    "Higher/lower power with identical design & size": {
        "IEC 61215": [
            "Performance at STC (MQT 06.1)",
            "Stabilization (MQT 19) for lower power models",
            "Hot-spot endurance test (MQT 09)",
            "TC200 (MQT 11)",
            "BPDT (MQT 18)",
        ],
        "IEC 61730": ["RCOT (MST 26)"],
    },
    "Increase OCPR (over-current protection rating)": {
        "IEC 61215": [],
        "IEC 61730": ["Continuity test of equipotential bonding (MST 13)", "RCOT (MST 26)"],
    },
    "Increase system voltage >5%": {
        "IEC 61215": [
            "Hot-spot endurance test (MQT 09)",
            "UV15 (MQT 10)",
            "DMLT (MQT 20)",
            "TC50 (MQT 11)",
            "HF10 (MQT 12)",
            "DH1000 (MQT 13)",
            "TC200 (MQT 11)",
            "PID (MQT 21)",
        ],
        "IEC 61730": [
            "Insulation thickness (MST 04)",
            "Accessibility test (MST 11)",
            "Module breakage test (MST 32)",
            "Continuity test of equipotential bonding (MST 13)",
            "Impulse voltage test (MST 14)",
            "Sequence B",
        ],
    },
    "Cell fixing / internal insulation tape change": {
        "IEC 61215": ["HF10 (MQT 12)"],
        "IEC 61730": [],
    },
    "External label/marking material change": {
        "IEC 61215": [],
        "IEC 61730": ["Sequence B", "Durability of markings (MST 05)"],
    },
    "Monofacial ↔ Bifacial change": {
        "IEC 61215": [
            "Hot-spot endurance test (MQT 09)",
            "UV15 (MQT 10)",
            "DMLT (MQT 20)",
            "TC50 (MQT 11)",
            "HF10 (MQT 12)",
            "BPDT (MQT 18.1)",
            "Performance at low irradiance (MQT 07)",
            "Measurement of temperature coefficients (MQT 04)",
            "TC200 (MQT 11)",
            "PID (MQT 21)",
        ],
        "IEC 61730": ["Dielectric & Insulation", "Grounding & Earthing", "Accessibility & Marking"],
    },
}

# For thin-film (MLI), simplified placeholders – align with the official matrix.
MLI_MATRIX = {
    "Frontsheet change": {
        "IEC 61215": ["UV (MQT 10)", "DH (MQT 13)", "TC (MQT 11)", "HF (MQT 12)", "MQT 01", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation", "Fire/Flammability (as applicable)"],
    },
    "Backsheet change": {
        "IEC 61215": ["UV (MQT 10)", "DH (MQT 13)", "TC (MQT 11)", "HF (MQT 12)", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation"],
    },
    "Electrical termination change": {
        "IEC 61215": ["Wet leakage (MQT 15)", "MQT 01", "MQT 02"],
        "IEC 61730": ["Wiring & Terminations", "Dielectric & Insulation"],
    },
    "Module size change": {
        "IEC 61215": ["MQT 10", "MQT 20", "Hail (MQT 17)", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation"],
    },
}

# -----------------------------
# Editable per-test sample counts (defaults are blank; you fill from IEC 61215/61730)
# -----------------------------
DEFAULT_SAMPLES = {
    # Example: "MQT 13": "10"
}

# -----------------------------
# App UI
# -----------------------------
st.title("IEC TS 62915:2023 Retesting Planner")
st.markdown("""
This tool helps plan **retesting** when **design/BOM** or **system rating** changes occur for PV modules.
**Final sequences and sample counts must be confirmed** with the official IEC TS 62915:2023 matrix and the
invoked standards **IEC 61215:2021** and **IEC 61730:2023**.
""")

with st.expander("Standards scope & reminders", expanded=False):
    st.markdown("""
- **62915:2023 (Ed. 2.0)**: Retesting framework & matrix for typical modifications; clarifies **MQT 20** and **MQT 21**; separates 61215 vs 61730 retest paths.
- **Sample counts & pass/fail**: Taken from **IEC 61215**/**IEC 61730**. Consider representative sampling where allowed.
- **Electrical terminations**: See **IEC 61730-2 (Clause 6)** and **IEC 61215-1 (Clause 4)**; apply **COR1:2024** updates.
- **QMS & components**: Ensure **IEC 62941**; consider **IEC 62788-1/-2** for sub-components.
""")

with st.sidebar:
    st.header("Inputs")
    tech = st.selectbox("Module technology", ["WBT (crystalline/wafer-based)", "MLI (thin-film)"])
    matrix = WBT_MATRIX if tech.startswith("WBT") else MLI_MATRIX

    mods = st.multiselect(
        "Select the design/BOM changes",
        options=list(matrix.keys()),
        help="Pick all applicable modifications for this retest planning session."
    )

    st.markdown("---")
    st.subheader("New material/component combination?")
    new_combo = st.checkbox(
        "YES – New combination of materials/components (e.g., new J-box + cable + connector)",
        value=False,
        help="Adds relevant IEC 61730 wiring/termination safety checks."
    )

    st.markdown("---")
    st.subheader("Conservatism")
    conservative = st.checkbox(
        "Use conservative add-ons (include MQT 01/02 & wet leakage where uncertain)",
        value=True
    )

    st.markdown("---")
    st.subheader("Sample counts (optional)")
    st.caption("Enter per-test minimums from IEC 61215/61730; leave blank to keep unspecified.")
    test_list_all = sorted(set(t for m in matrix.values() for t in (m["IEC 61215"] + m["IEC 61730"])))
    sample_inputs = {}
    for t in test_list_all:
        sample_inputs[t] = st.text_input(f"Samples for {t}", value=str(DEFAULT_SAMPLES.get(t, "")), key=f"s_{t}")

st.markdown("### Recommended retest plan")
if not mods:
    st.info("Select at least one modification in the sidebar to see the recommended plan.")
else:
    # Build the plan
    plan_61215 = []
    plan_61730 = []

    for m in mods:
        plan_61215.extend(matrix[m]["IEC 61215"])
        plan_61730.extend(matrix[m]["IEC 61730"])

    if new_combo:
        # Emphasize 61730 wiring/terminations when new component combinations are used
        plan_61730.extend(["Wiring & Terminations", "Dielectric & Insulation"])

    # Deduplicate while preserving order
    def dedupe(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    plan_61215 = dedupe(plan_61215)
    plan_61730 = dedupe(plan_61730)

    # Conservative add-ons
    if conservative:
        if "MQT 01" not in plan_61215:
            plan_61215.insert(0, "MQT 01")
        if "MQT 02" not in plan_61215:
            plan_61215.append("MQT 02")
        if "Wet leakage (MQT 15)" not in plan_61215 and ("Dielectric & Insulation" in plan_61730):
            plan_61215.append("Wet leakage (MQT 15)")

    # Helper to derive descriptions from labels
    def get_description_from_label(lbl: str) -> str:
        desc = describe_label(lbl)
        return desc

    # Build dataframes
    def build_df(tests, standard):
        rows = []
        for t in tests:
            # UI-friendly label (clean up any HTML entities if present)
            label = t.replace("&amp;", "&")
            rows.append({
                "Standard": standard,
                "Test / Check": label,
                "Description": get_description_from_label(label),
                "Planned samples (min)": sample_inputs.get(t, "").strip()
            })
        return pd.DataFrame(rows)

    df_61215 = build_df(plan_61215, "IEC 61215")
    df_61730 = build_df(plan_61730, "IEC 61730")

    tabs = st.tabs(["IEC 61215 (Design Qualification)", "IEC 61730 (Safety)"])
    with tabs[0]:
        st.dataframe(df_61215, use_container_width=True)
    with tabs[1]:
        st.dataframe(df_61730, use_container_width=True)

    st.markdown("#### Edit the plan (optional)")
    st.caption("Use the editor below to fine-tune tests and sample counts before exporting.")
    df_edit = pd.concat([df_61215, df_61730], ignore_index=True)
    edited = st.data_editor(df_edit, use_container_width=True, num_rows="dynamic")

    # Export
    def to_excel(df: pd.DataFrame):
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Retest plan")
        buf.seek(0)
        return buf

    st.markdown("#### Export")
    csv = edited.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", data=csv, file_name="iec62915_retest_plan.csv", mime="text/csv")
    xls = to_excel(edited)
    st.download_button("Download Excel (.xlsx)", data=xls, file_name="iec62915_retest_plan.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.markdown("---")
st.markdown("""
**Disclaimer & next steps**

- Treat these as **indicative** sequences; align with the **official IEC TS 62915:2023 matrix** (XLS attachment) and
  execute per the exact **IEC 61215:2021 / IEC 61730:2023** requirements, including **test sharing** rules and **sample allocations**.
- For **electrical terminations** retests, ensure compliance with **IEC 61730-2 Clause 6** and **IEC 61215-1 Clause 4** (per **COR1:2024**).
- Maintain a **QMS** in accordance with **IEC 62941**; for sub-components, consider **IEC 62788-1/-2**.
""")
