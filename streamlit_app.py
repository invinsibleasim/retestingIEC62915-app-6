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

import streamlit as st
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="IEC TS 62915:2023 Retesting Planner", layout="wide")

# -----------------------------
# Reference: MQT test dictionary (descriptions are brief & generic for planning)
# -----------------------------
MQT_INFO = {
    "MQT 01": "Visual inspection",
    "MQT 02": "Maximum power determination (STC) / Performance check",
    "MQT 10": "Mechanical load (static) - front/back",
    "MQT 20": "Cyclic (dynamic) mechanical load (added/clarified in 2023 ed.)",
    "MQT 21": "Potential-induced degradation (PID)",
    "TC": "Thermal cycling",
    "HF": "Humidity freeze",
    "DH": "Damp heat",
    "UV": "UV preconditioning",
    "Hail": "Hail impact",
    "Bypass/Hot-spot": "Bypass diode and hot-spot endurance checks",
    "Wet leakage": "Wet leakage current test (61215; safety linkage in 61730)",
}

# -----------------------------
# Reference: IEC 61730 (Safety) - planning categories (generic labels)
# -----------------------------
SAFETY_INFO = {
    "Dielectric & Insulation": "Dielectric withstand and insulation/wet leakage checks",
    "Bypass diode thermal": "Bypass diode thermal test / reverse-current related checks",
    "Accessibility & Marking": "Label durability/marking/ratings checks",
    "Wiring & Terminations": "J-box/cable/connector compatibility and safety tests (61730-2)",
    "Fire/Flammability (as applicable)": "Where applicable per product category",
    "Grounding & Earthing": "Bonding continuity and earthing provisions",
}

# -----------------------------
# Indicative retest matrix for WAfer-Based Technology (WBT) modules
# (Engineering judgment placeholders – please align with the official 62915 XLS matrix)
# -----------------------------
WBT_MATRIX = {
    "Frontsheet change": {
        "IEC 61215": ["UV", "DH", "TC", "HF", "MQT 01", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation", "Fire/Flammability (as applicable)", "Accessibility & Marking"],
    },
    "Encapsulant (EVA/POE) change or stack change": {
        "IEC 61215": ["UV", "DH", "TC", "HF", "MQT 21", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation", "Accessibility & Marking"],
    },
    "Cell technology change (e.g., PERC → TOPCon/HJT)": {
        "IEC 61215": ["TC", "HF", "DH", "Bypass/Hot-spot", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation"],
    },
    "Interconnect/ribbon/paste change": {
        "IEC 61215": ["TC", "MQT 20", "MQT 10", "MQT 02"],
        "IEC 61730": [],
    },
    "Backsheet change": {
        "IEC 61215": ["UV", "DH", "TC", "HF", "MQT 02"],
        "IEC 61730": ["Fire/Flammability (as applicable)", "Dielectric & Insulation", "Accessibility & Marking"],
    },
    "Electrical termination (J-box/cable/connector) change": {
        "IEC 61215": ["Wet leakage", "MQT 01", "MQT 02"],
        "IEC 61730": ["Wiring & Terminations", "Dielectric & Insulation", "Grounding & Earthing"],
    },
    "Bypass diode change": {
        "IEC 61215": ["Bypass/Hot-spot", "MQT 02"],
        "IEC 61730": ["Bypass diode thermal", "Dielectric & Insulation"],
    },
    "Edge seal change": {
        "IEC 61215": ["DH", "HF", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation"],
    },
    "Frame/mounting redesign": {
        "IEC 61215": ["MQT 10", "MQT 20", "Hail", "MQT 02"],
        "IEC 61730": ["Grounding & Earthing", "Accessibility & Marking"],
    },
    "Module size change": {
        "IEC 61215": ["MQT 10", "MQT 20", "Hail", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation"],
    },
    "Higher/lower power with identical design & size": {
        "IEC 61215": ["MQT 02", "Bypass/Hot-spot"],
        "IEC 61730": [],
    },
    "Increase OCPR (over-current protection rating)": {
        "IEC 61215": ["Bypass/Hot-spot", "MQT 02"],
        "IEC 61730": ["Bypass diode thermal", "Accessibility & Marking"],
    },
    "Increase system voltage >5%": {
        "IEC 61215": ["Wet leakage", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation"],
    },
    "Cell fixing / internal insulation tape change": {
        "IEC 61215": ["TC", "DH", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation"],
    },
    "External label/marking material change": {
        "IEC 61215": [],
        "IEC 61730": ["Accessibility & Marking"],
    },
    "Monofacial ↔ Bifacial change": {
        "IEC 61215": ["UV", "DH", "TC", "HF", "MQT 10", "MQT 20", "Hail", "Wet leakage", "Bypass/Hot-spot", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation", "Grounding & Earthing", "Accessibility & Marking"],
    },
}

# For thin-film (MLI), start with a simplified placeholder mapping; you should align with the official matrix.
MLI_MATRIX = {
    "Frontsheet change": {
        "IEC 61215": ["UV", "DH", "TC", "HF", "MQT 01", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation", "Fire/Flammability (as applicable)"],
    },
    "Backsheet change": {
        "IEC 61215": ["UV", "DH", "TC", "HF", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation"],
    },
    "Electrical termination change": {
        "IEC 61215": ["Wet leakage", "MQT 01", "MQT 02"],
        "IEC 61730": ["Wiring & Terminations", "Dielectric & Insulation"],
    },
    "Module size change": {
        "IEC 61215": ["MQT 10", "MQT 20", "Hail", "MQT 02"],
        "IEC 61730": ["Dielectric & Insulation"],
    },
}

# -----------------------------
# Editable per-test sample counts (defaults are blank; you fill from IEC 61215/61730)
# -----------------------------
DEFAULT_SAMPLES = {
    # Leave blank; users provide per their invoked standard tables or internal CB agreements.
    # Example: "DH": 10
}

# -----------------------------
# App UI
# -----------------------------
st.title("IEC TS 62915:2023 Retesting Planner")
st.markdown("""
This tool helps plan **retesting** when **design/BOM** or **system rating** changes occur for PV modules.
**Final sequences and sample counts must be confirmed with the official IEC TS 62915:2023 matrix and the
invoked standards IEC 61215:2021 and IEC 61730:2023.**
""")

with st.expander("Standards scope & reminders", expanded=False):
    st.markdown("""
- **62915:2023 (Ed. 2.0)**: Provides a retesting framework and a matrix for typical modifications.
  It clarifies inclusion of **MQT 20 (Cyclic/Dynamic ML)** and **MQT 21 (PID)**; separates 61215 vs 61730 retest paths.
- **Sample counts & pass/fail**: Taken from **IEC 61215** and **IEC 61730**. Consider representative sampling where allowed.
- **Electrical terminations**: See **IEC 61730-2 (Clause 6)** and **IEC 61215-1 (Clause 4)**; apply **COR1:2024** updates.
- **QMS & component references**: Ensure **IEC 62941** quality system; consider **IEC 62788-1/-2** for sub-components.
""")

with st.sidebar:
    st.header("Inputs")
    tech = st.selectbox("Module technology", ["WBT (crystalline/wafer-based)", "MLI (thin-film)"])

    if tech.startswith("WBT"):
        matrix = WBT_MATRIX
    else:
        matrix = MLI_MATRIX

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
        if "MQT 01" not in plan_61215: plan_61215.insert(0, "MQT 01")
        if "MQT 02" not in plan_61215: plan_61215.append("MQT 02")
        if "Wet leakage" not in plan_61215 and ("Dielectric & Insulation" in plan_61730):
            plan_61215.append("Wet leakage")

    # Build dataframes
    def build_df(tests, standard):
        rows = []
        for t in tests:
            rows.append({
                "Standard": standard,
                "Test / Check": t,
                "Description": MQT_INFO.get(t, SAFETY_INFO.get(t, "")),
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
    st.download_button("Download Excel (.xlsx)", data=xls, file_name="iec62915_retest_plan.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.markdown("---")
st.markdown("""
**Disclaimer & next steps**

- Treat these as **indicative** sequences; align with the **official IEC TS 62915:2023 matrix** (XLS attachment) and
  execute per the exact **IEC 61215:2021 / IEC 61730:2023** requirements, including **test sharing** rules and **sample allocations**.
- For **electrical terminations** retests, ensure compliance with **IEC 61730-2 Clause 6** and **IEC 61215-1 Clause 4**
  (per **COR1:2024**).  
- Maintain a **QMS** in accordance with **IEC 62941**; for sub-components, consider **IEC 62788-1/-2**.
""")
