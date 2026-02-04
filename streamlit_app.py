# streamlit_app.py
# IEC TS 62915:2023 Retesting Planner + Costing (with your detailed task list)
# Author: Asim's Copilot (M365)
# -------------------------------------------------------------------------
# PURPOSE
# - Load a retesting task list (from demo, upload, or paste)
# - Compute durations (hours/days) & costs with configurable assumptions
# - Filter by component change, standard, and search terms
# - Edit inline and export CSV/XLSX
#
# IMPORTANT STANDARDS NOTES (for users & auditors):
# - IEC TS 62915:2023 provides retesting frameworks & a matrix that references IEC 61215 (2021) and IEC 61730 (2023).
#   It highlights/addresses tests like MQT 20 (dynamic mechanical) and MQT 21 (PID) in retesting programs.
#   Source: IEC Webstore summary and companion descriptions.  [CITE: turn1search7, turn1search5]
# - Number of samples and pass/fail criteria are taken from IEC 61215/61730, not 62915.  [CITE: turn1search3, turn1search7]
# - Corrigendum 1 (2024) clarifies electrical terminations references to IEC 61730-2 Clause 6 / IEC 61215-1 Clause 4.  [CITE: turn1search2]
#
# DISCLAIMER:
# - Your dataset below is treated as a planning input. Always align final sequences & counts with the official IEC matrix and CB agreements.

import streamlit as st
import pandas as pd
import numpy as np
from io import StringIO, BytesIO

st.set_page_config(page_title="IEC TS 62915:2023 Retesting Planner + Costing", layout="wide")

# ----------------------------
# Demo data (your table pasted as TSV)
# ----------------------------
DEMO_TSV = r"""
Critical component list    Test Description    Standard    Time (hrs) per one module    Frequency    Quantity    Duration in Hours    Operational Time    Duration in days    Cost per test    Total Cost    Equipment, Software required    Remarks    Sub-contracting required
Modification to frontsheet/Glass    Visual inspection (MQT 01)    61215    0.5    11    6    33    8    4.125                    
Modification to frontsheet/Glass    Performance at STC (MQT 06.1)    61215    0.5    11    6    33    8    4.125                    
Modification to frontsheet/Glass    Insulation test (MQT 03)    61215    0.5    2    6    6    8    0.75                    
Modification to frontsheet/Glass    Wet leakage current test (MQT 15)    61215    0.5    11    6    33    8    4.125                    
Modification to frontsheet/Glass    Initial Stabilization (MQT 19)    61215    48    3    6    144    8    18                    
Modification to frontsheet/Glass    Hot-spot endurance test (MQT 09)    61215    48    1    1    48    8    6                change in material, strengthening process or if thickness is reduced.    
Modification to frontsheet/Glass    UV preconditioning test (MQT 10)    61215    72    1    2    72    24    3                Entire sequence can be omitted for glass with λcUV at or above the glass which was previously tested.    
Modification to frontsheet/Glass    Cyclic (dynamic) mechanical load test (MQT 20)    61215    3    1    2    6    8    0.75                Entire sequence can be omitted for glass with λcUV at or above the glass which was previously tested.    
Modification to frontsheet/Glass    Thermal cycling test, 50 cycles (MQT 11)    61215    264    1    1    264    24    11                Entire sequence can be omitted for glass with λcUV at or above the glass which was previously tested.    
Modification to frontsheet/Glass    Humidity freeze test (MQT 12)    61215    264    1    1    264    24    11                Entire sequence can be omitted for glass with λcUV at or above the glass which was previously tested.    
Modification to frontsheet/Glass    Retention of junction box on mounting surface (MQT 14.1)    61215    1    1    1    1    8    0.125                MQT 14.1 can be omitted if junction box is not mounted on the frontsheet or for change in glass thickness    
Modification to frontsheet/Glass    Damp heat test (MQT 13)    61215    1050    1    2    1050    24    43.75                if non-glass or if surface treatment is added/changed (inside or outside)    
Modification to frontsheet/Glass    Final Stabilization (MQT 19)    61215    48    1    3    48    24    2                    
Modification to frontsheet/Glass    Bending Test (MQT 22)    61215    1    1    1    1    8    0.125                "if non-glass and if module is considered to be “flexible” per the definition specified in IEC 61215
Can be omitted for changes related only to outside surface treatment"    
Modification to frontsheet/Glass    Static mechanical load test (MQT 16)    61215    12    1    1    12    8    1.5                can be omitted for different outside surface treatments.    
Modification to frontsheet/Glass    Hail test (MQT 17)    61215    48    1    1    48    12    4                can be omitted for different surface treatment.    
Modification to frontsheet/Glass    Visual inspection (MST 01)    61730    0.5    4    5    10    8    1.25                    
Modification to frontsheet/Glass    Maximum power determination (MST 03)    61730    0.5    4    5    10    8    1.25                    
Modification to frontsheet/Glass    Insulation test (MST 16)    61730    0.5    4    5    10    8    1.25                    
Modification to frontsheet/Glass    Wet leakage current test (MST 17)    61730    0.5    4    5    10    8    1.25                    
Modification to frontsheet/Glass    Insulation thickness test (MST 04)    61730    0.5    2    2    2    8    0.25                if non-glass    
Modification to frontsheet/Glass    Cut susceptibility test (MST 12)    61730    0.5    1    2    1    8    0.125                if non-glass    
Modification to frontsheet/Glass    Impulse voltage test (MST 14)    61730    0.5    1    1    0.5    8    0.0625                if non-glass and reduced thickness or if change in material    
Modification to frontsheet/Glass    Ignitability test (MST 24)    61730    0.5    1    1    0.5    8    0.0625                if non-glass    
Modification to frontsheet/Glass    Module breakage test (MST 32)    61730    0.5    1    1    0.5    8    0.0625                can be omitted for different surface treatments that do not impair mechanical strength    
Modification to frontsheet/Glass    Peel test (MST 35) or Lap shear strength test (MST 36)    61730    0.5    1    1    0.5    8    0.0625                if design includes cemented joint (not for change of thickness, not for different outer surface treatment and not for change in glass strengthening process)    
Modification to frontsheet/Glass    Materials creep test (MST 37)    61730    72    1    1    72    24    3                For more than 10 % increase in glass thickness and 20 % for non-glass thickness, frameless modules only (not required for framed modules).    
Modification to frontsheet/Glass    Sequence B    61730                0                if non-glass    
Modification to frontsheet/Glass    Sequence B1    61730                0                if design qualified for pollution degree 1 (not for reduction of thickness, not for different outside surface treatment and not for change in glass strengthening process)    
Modification to encapsulation system    Hot-spot endurance test (MQT 09)    61215    48    1    1    48    24    2                    
Modification to encapsulation system    UV preconditioning test (MQT 10)    61215    96    1    1    96    24    4                    
Modification to encapsulation system    Cyclic (dynamic) mechanical load test (MQT 20)    61215    3    1    1    3    8    0.375                Can omit cyclic (dynamic) mechanical load test (MQT 20) for change in amount or type of additives but same material    
Modification to encapsulation system    Thermal cycling test, 50 cycles (MQT 11)    61215    264    1    1    264    24    11                    
Modification to encapsulation system    Humidity freeze test (MQT 12)    61215    264    1    1    264    24    11                    
Modification to encapsulation system    Thermal cycling test, 200 cycles (MQT 11)    61215    720    1    1    720    24    30                Only required if reduction in thickness or g/m2 by more than 20 %    
Modification to encapsulation system    Damp heat test (MQT 13)    61215    1050    1    1    1050    24    43.75                    
Modification to encapsulation system    Hail test (MQT 17)    61215    48    1    1    48    12    4                "if frontsheet is polymeric
Can omit hail test (MQT 17) for change in amount or type of additives but same material"    
Modification to encapsulation system    Potential induced degradation test (MQT 21)    61215    96    1    1    96    24    4                If volume resistivity (according to IEC 62788-1-2) specified for the sunny-side or rearside stack decreases by more than 1 order of magnitude (e.g. 10^17 Ω-m vs. 10^18 Ω-m)    
Modification to encapsulation system    Bending Test (MQT 22)    61215    1    1    1    1    8    0.125                if module is considered to be “flexible” per the definition specified in IEC 61215    
Modification to encapsulation system    Cut susceptibility test (MST 12)    61730    0.5    1    1    1    8    0.125                if frontsheet or backsheet is polymeric    
Modification to encapsulation system    Impulse voltage test (MST 14)    61730    1    1    1    1    8    0.125                if reduced thickness or if different material    
Modification to encapsulation system    Module breakage test (MST 32)    61730    0.5    1    1    0.5    8    0.0625                if material composition changes    
Modification to encapsulation system    Peel test (MST 35) or Lap shear strength test (MST 36)    61730    0.5    1    1    0.5    8    0.0625                if design includes encapsulant as a part of a qualified cemented joint    
Modification to encapsulation system    Materials creep test (MST 37)    61730    72    1    1    72    24    3                    
Modification to encapsulation system    Sequence B    61730                0                only for different material or reduction in thickness    
Modification to encapsulation system    Sequence B1    61730                0                if design qualified for pollution degree 1    
Modification to cell technology    Cyclic (dynamic) mechanical load test (MQT 20)    61215    3    1    1    3    8    0.375                    
Modification to cell technology    Thermal cycling test, 50 cycles (MQT 11)    61215    264    1    1    264    24    11                    
Modification to cell technology    Humidity freeze test (MQT 12)    61215    264    1    1    264    24    11                    
Modification to cell technology    Potential-Induced Degradation (MQT 21)    61215    96    1    1    1    24    0.041666667                only for change in technology, i.e. semiconductor layer material, anti-reflective (AR) coating, crystallization, or different manufacturer    
Modification to cell technology    Hot-spot endurance test (MQT 09)    61215    48    1    1    48    24    2                    
Modification to cell technology    Thermal cycling test, 200 cycles (MQT 11)    61215    720    1    1    720    24    30                    
Modification to cell technology    Damp heat test (MQT 13)    61215    1050    1    1    1050    24    43.75                may be omitted for change in crystallization or if outer surface of cell is chemically identical (metallization and AR coating)    
Modification to cell technology    Static mechanical load test (MQT 16)    61215    10    1    1    10    8    1.25                for reduction of cell thickness or change in crystallization only    
Modification to cell technology    Hail test (MQT 17)    61215    48    1    1    48    12    4                for reduction of cell thickness only    
Modification to cell technology    Bending Test (MQT 22)    61215    1    1    1    1    8    0.125                if module is considered to be “flexible” per the definition specified in IEC 61215    
Modification to cell technology    Reverse current overload test (MST 26)    61730    4    1    1    4    8    0.5                Can be omitted for crystallization    
Modification to cell and string interconnect material    Hot-spot endurance test (MQT 09)    61215    48    1    1    48    24    2                for changes in bonding technique, interconnect material, solder material, flux or conductive adhesive    
Modification to cell and string interconnect material    Thermal cycling test, 200 cycles (MQT 11)    61215    720    1    1    720    24    30                    
Modification to cell and string interconnect material    Damp heat test (MQT 13)    61215    1050    1    1    1050    24    43.75                for changes in material or for different solder paste/wire, flux, or conductive adhesive    
Modification to cell and string interconnect material    Reverse current overload test (MST 26)    61730    4    1    1    4    8    0.5                    
Modification to backsheet    Hot-spot endurance test (MQT 09)    61215    48    1    1    48    24    2                for glass if change in heat strengthening process or for non-glass if thickness is reduced or different material.    
Modification to backsheet    UV preconditioning test (MQT 10)    61215    96    1    1    96    24    4                Entire sequence can be omitted for glass with λcUV at or above the glass which was previously tested.    
Modification to backsheet    Cyclic (dynamic) mechanical load test (MQT 20)    61215    3    1    1    3    8    0.375                Entire sequence can be omitted for glass with λcUV at or above the glass which was previously tested.    
Modification to backsheet    Thermal cycling test, 50 cycles (MQT 11)    61215    264    1    1    264    24    11                Entire sequence can be omitted for glass with λcUV at or above the glass which was previously tested.    
Modification to backsheet    Humidity freeze test (MQT 12)    61215    264    1    1    264    24    11                Entire sequence can be omitted for glass with λcUV at or above the glass which was previously tested.    
Modification to backsheet    Retention of junction box on mounting surface (MQT 14.1)    61215    1    1    1    1    8    0.125                MQT 14.1 can be omitted if junction box is not mounted on the frontsheet or for change in glass thickness    
Modification to backsheet    Damp heat test (MQT 13)    61215    1050    1    1    1050    24    43.75                if non-glass or if surface treatment is added/changed (inside or outside)    
Modification to backsheet    Bending Test (MQT 22)    61215    1    1    1    1    1    1                "if non-glass and if module is considered to be “flexible” per the definition specified in IEC 61215
Can be omitted for changes related only to outside surface treatment"    
Modification to backsheet    Static mechanical load test (MQT 16)    61215    10    1    1    10    8    1.25                "if glass (including change in manufacturer) or if
mounting (as described in the manufacturer’s installation manual) depends on adhesion to
backsheet"    
Modification to backsheet    Hail test (MQT 17)    61215    48    1    1    48    12    4                if rigidity depends on backsheet.    
Modification to backsheet    Insulation thickness test (MST 04)    61730    1    1    1    1    8    0.125                if non-glass    
Modification to backsheet    Cut susceptibility test (MST 12)    61730    0.5    1    1    0.5    8    0.0625                if non-glass    
Modification to backsheet    Impulse voltage test (MST 14)    61730    1    1    1    1    8    0.125                if non-glass and reduced thickness or if change in material    
Modification to backsheet    Ignitability test (MST 24)    61730    1    1    1    1    8    0.125                if non-glass    
Modification to backsheet    Module breakage test (MST 32)    61730    0.5    1    1    0.5    8    0.0625                if glass (can be omitted for different surface treatments that do not impair mechanical strength)    
Modification to backsheet    Peel test (MST 35) or Lap shear strength test (MST 36)    61730    1    1    1    1    8    0.125                "if design includes cemented joint
and if backsheet is part of it (not for reduction of glass thickness or heat strengthening)"    
Modification to backsheet    Materials creep test (MST 37)    61730    72    1    1    72    24    3                (not for reduction of thickness and not for different outside surface treatment)    
Modification to backsheet    Sequence B    61730                0                if non-glass    
Modification to backsheet    Sequence B1    61730                0                if design qualified for pollution degree 1 (not for reduction of thickness, not for different outside surface treatment and not for change in glass strengthening process)    
Modification to electrical termination (such as junction box, cables and connectors)    UV preconditioning test (MQT 10)    61215    96    1    1    96    24    4                UV preconditioning test can be omitted for change in potting material, change in number of junction boxes, or in case junction box is not directly exposed to sunlight    
Modification to electrical termination (such as junction box, cables and connectors)    Cyclic (dynamic) mechanical load test (MQT 20)    61215    3    1    1    3    8    0.375                Cyclic (dynamic) mechanical load test can be omitted for different cable or connector, different material of cable or connector, or different potting material    
Modification to electrical termination (such as junction box, cables and connectors)    Thermal cycling test, 50 cycles (MQT 11)    61215    264    1    1    264    24    11                    
Modification to electrical termination (such as junction box, cables and connectors)    Humidity freeze test (MQT 12)    61215    264    1    1    264    24    11                    
Modification to electrical termination (such as junction box, cables and connectors)    Retention of junction box on mounting surface (MQT 14.1 and 14.2)    61215    1    1    1    1    8    0.125                "Test of cord anchorage (MQT 14.2) can be omitted:
– If junction box has already been pre-qualified
– for change in mechanical attachment of junction box to the mounting surface or change in number of junction boxes
– for changed position or if re-located from rearside to frontside (or vice versa)
– Retention of junction box on mounting surface (MQT 14.1) can be omitted for change in
electrical attachment of cables or change in number of junction boxes"    
Modification to electrical termination (such as junction box, cables and connectors)    Thermal cycling test, 200 cycles (MQT 11)    61215    720    1    1    720    24    30                only for change in electrical attachment    
Modification to electrical termination (such as junction box, cables and connectors)    Damp heat test (MQT 13)    61215    1050    1    1    1050    24    43.75                    
Modification to electrical termination (such as junction box, cables and connectors)    Bypass diode thermal test (MQT 18)    61215    12    1    1    12    8    1.5                (not required for change of any attachment, change from frontside to rearside (or vice versa), or change in position)    
Modification to electrical termination (such as junction box, cables and connectors)    Accessibility test (MST 11)    61730    1    1    1    1    8    0.125                    
Modification to electrical termination (such as junction box, cables and connectors)    Ignitability test (MST 24)    61730    1    1    1    1    8    0.125                only for change of adhesive    
Modification to electrical termination (such as junction box, cables and connectors)    Reverse current overload test (MST 26)    61730    4    1    1    4    8    0.5                (not for change of adhesive)    
Modification to electrical termination (such as junction box, cables and connectors)    Screw connections test (MST 33)    61730    0.5    1    1    0.5    8    0.0625                if applicable    
Modification to electrical termination (such as junction box, cables and connectors)    Evaluation of insulation coordination (MST 57 10.34.3.5)    61730    3    1    1    3    8    0.375                if design includes a cemented joint (only for mechanical attachment of junction box)    
Modification to electrical termination (such as junction box, cables and connectors)    Peel test (MST 35) or Lap shear strength test (MST 36)    61730    1    1    1    1    8    0.125                if design includes cemented joint for mechanical attachment of junction box.    
Modification to electrical termination (such as junction box, cables and connectors)    Materials creep test (MST 37)    61730    72    1    1    72    24    3                only for change of adhesive or for increased weight of electrical termination    
Modification to electrical termination (such as junction box, cables and connectors)    Sequence B    61730                0                only for change of adhesive    
Modification to electrical termination (such as junction box, cables and connectors)    Sequence B1    61730                0                if design qualified for pollution degree 1    
Modification to bypass diode    Hot-spot endurance test (MQT 09)    61215    48    1    1    48    24    2                only for different number of cells connected in series across a bypass diode in any of the sub-circuits of a PV module    
Modification to bypass diode    Thermal cycling test, 200 cycles (MQT 11)    61215    720    1    1    720    24    30                only for different mounting method    
Modification to bypass diode    Bypass diode thermal test (MQT 18)    61215    12    1    1    12    8    1.5                    
Modification to bypass diode    Reverse current overload test (MST 26)    61730    4    1    1    4    8    0.5                only for different mounting method    
Modification to electrical circuitry (e.g. more cells per bypass diode or rerouting of output leads)    Hot-spot endurance test (MQT 09)    61215    48    1    1    48    24    2                only if more cells per bypass diode    
Modification to electrical circuitry (e.g. more cells per bypass diode or rerouting of output leads)    Thermal cycling test, 200 cycles (MQT 11)    61215    720    1    1    720    24    30                if there are internal conductors behind the cells    
Modification to electrical circuitry (e.g. more cells per bypass diode or rerouting of output leads)    Bypass diode thermal test (MQT 18)    61215    12    1    1    12    8    1.5                if the short circuit current increases by >10 %    
Modification to electrical circuitry (e.g. more cells per bypass diode or rerouting of output leads)    Cut susceptibility test (MST 12)    61730    0.5    1    1    0.5    8    0.0625                for rerouting of output leads for modules with polymeric backsheets or frontsheets.    
Modification to electrical circuitry (e.g. more cells per bypass diode or rerouting of output leads)    insulation thickness test (MST 04)    61730    1    1    1    1    8    0.125                for rerouting of output leads for modules with polymeric backsheets or frontsheets.    
Modification to electrical circuitry (e.g. more cells per bypass diode or rerouting of output leads)    Reverse current overload test (MST 26)    61730    4    1    1    4    8    0.5                (only for increase in PV module operating voltage/current by 10 % or more)    
Modification to edge sealing    UV preconditioning test (MQT 10)    61215    96    1    1    96    24    4                if edge sealing is outer enclosure    
Modification to edge sealing    Thermal cycling test, 50 cycles (MQT 11)    61215    264    1    1    264    24    11                if edge sealing is outer enclosure    
Modification to edge sealing    Humidity freeze test (MQT 12)    61215    264    1    1    264    24    11                if edge sealing is outer enclosure    
Modification to edge sealing    Impulse voltage test (MST 14)    61730    1    1    1    1    8    0.125                    
Modification to edge sealing    Ignitability test (MST 24)    61730    1    1    1    1    8    0.125                (not for different thickness or width) and only if edge seal is accessible for flame impingement    
Modification to edge sealing    Peel test (MST 35) or Lap shear strength test (MST 36)    61730    1    1    1    1    8    0.125                If design includes cemented joint    
Modification to edge sealing    Sequence B    61730                0                not for different thickness or width    
Modification to edge sealing    Sequence B1    61730                0                if design qualified for pollution degree 1    
Modification to frame and/or mounting structure    UV preconditioning test (MQT 10)    61215    96    1    1    96    24    4                "(UV preconditioning shall be omitted if adhesive is not exposed to direct sunlight)
Only for changes in frame adhesive or changes to the material, shape, and/or crosssection of the frame mounting material (if polymeric)"    
Modification to frame and/or mounting structure    Cyclic (dynamic) mechanical load test (MQT 20)    61215    3    1    1    3    8    0.375                Only for changes in frame adhesive or changes to the material, shape, and/or crosssection of the frame mounting material (if polymeric)    
Modification to frame and/or mounting structure    Thermal cycling test, 50 cycles (MQT 11)    61215    264    1    1    264    24    11                Only for changes in frame adhesive or changes to the material, shape, and/or crosssection of the frame mounting material (if polymeric)    
Modification to frame and/or mounting structure    Humidity freeze test (MQT 12)    61215    264    1    1    264    24    11                Only for changes in frame adhesive or changes to the material, shape, and/or crosssection of the frame mounting material (if polymeric)    
Modification to frame and/or mounting structure    Damp heat test (MQT 13)    61215    1050    1    1    1050    24    43.75                "if mounting employs an adhesive or polymeric framing material or
if change from framed to frameless PV module or vice versa"    
Modification to frame and/or mounting structure    Static mechanical load test (MQT 16)    61215    10    1    1    10    8    1.25                    
Modification to frame and/or mounting structure    Hail test (MQT 17)    61215    48    1    1    48    12    4                if changing from non-polymeric to polymeric frame or if change from framed to frameless PV module    
Modification to frame and/or mounting structure    Continuity test of equipotential bonding (MST 13)    61730    1    1    1    1    8    0.125                if change in method of assembly (can be omitted if change only in adhesive)    
Modification to frame and/or mounting structure    Ignitability test (MST 24)    61730    1    1    1    1    8    0.125                for polymeric frames or if change in frame adhesive (can be omitted for change from one silicone to another silicone adhesive with polymer component >95 % silicone content)    
Modification to frame and/or mounting structure    Module breakage test (MST 32)    61730    1    1    1    1    8    0.125                    
Modification to frame and/or mounting structure    Screw connections test (MST 33)    61730    0.5    1    1    0.5    8    0.0625                 if applicable    
Modification to frame and/or mounting structure    Material creep test (MST 37)    61730    72    1    1    72    24    3                if creep is not prevented by frame or other support anymore    
Modification to frame and/or mounting structure    Sequence B    61730                0                for polymeric frames    
Change in PV module size    Thermal cycling test, 200 cycles (MQT 11)    61215    720    1    1    720    24    30                    
Change in PV module size    Damp heat test (MQT 13)    61215    1050    1    1    1050    24    43.75                    
Change in PV module size    Static mechanical load test (MQT 16)    61215    10    1    1    10    12    0.833333333                    
Change in PV module size    Hail test (MQT 17)    61215    48    1    1    48    12    4                if non-tempered glass or if non-glass    
Change in PV module size    Bending Test (MQT 22)    61215    1    1    1    1    8    0.125                if module is considered to be “flexible” per the definition specified in IEC 61215    
Change in PV module size    Reverse current overload test (MST 26)    61730    4    1    1    4    8    0.5                for MLI thin film modules ONLY    
Change in PV module size    Module breakage test (MST 32)    61730    1    1    1    1    8    0.125                    
Higher or lower output power with the identical design and size    Hot-spot endurance test (MQT 09)    61215    48    1    1    48    12    4                    
Higher or lower output power with the identical design and size    Thermal cycling test, 200 cycles (MQT 11)    61215    720    1    1    720    24    30                if short-circuit current is increased by more than 10%    
Higher or lower output power with the identical design and size    Bypass diode thermal test (MQT 18)    61215    12    1    1    12    8    1.5                if short-circuit current is increased by more than 10%    
Higher or lower output power with the identical design and size    Reverse current overload test (MST 26)    61730    4    1    1    4    8    0.5                    
Increase of over-current protection rating    Continuity test of equipotential bonding (MST 13)    61730    1    1    1    1    8    0.125                    
Increase of over-current protection rating    Reverse current overload test (MST 26)    61730    4    1    1    4    8    0.5                    
Increase of system voltage by more than 5 %    Hot-spot endurance test (MQT 09)    61215    48    1    1    48    12    4                    
Increase of system voltage by more than 5 %    UV preconditioning test (MQT 10)    61215    96    1    1    96    8    12                    
Increase of system voltage by more than 5 %    Cyclic (dynamic) mechanical load test (MQT 20)    61215    3    1    1    3    8    0.375                    
Increase of system voltage by more than 5 %    Thermal cycling test, 50 cycles (MQT 11)    61215    264    1    1    264    24    11                    
Increase of system voltage by more than 5 %    Humidity freeze test (MQT 12)    61215    264    1    1    264    24    11                    
Increase of system voltage by more than 5 %    Thermal cycling test, 200 cycles (MQT 11)    61215    720    1    1    720    24    30                    
Increase of system voltage by more than 5 %    Damp heat test (MQT 13)    61215    1050    1    1    1050    24    43.75                    
Increase of system voltage by more than 5 %    Potential induced degradation test (MQT 21)    61215    96    1    1    96    24    4                    
Increase of system voltage by more than 5 %    Re-evaluate creepage and clearance distances of conductors, and verify compliance through inspection and/or testing in accordance with insulation coordination requirements in IEC 61730-1    61730    2    1    1    2    8    0.25                    
Increase of system voltage by more than 5 %    Insulation thickness test (MST 04)    61730    1    1    1    1    8    0.125                    
Increase of system voltage by more than 5 %    Accessibility test (MST 11)    61730    1    1    1    1    8    0.125                    
Increase of system voltage by more than 5 %    Cut susceptibility test (MST 12) if non-glass    61730    1    1    1    1    8    0.125                    
Increase of system voltage by more than 5 %    Continuity test of equipotential bonding (MST 13)    61730    1    1    1    1    8    0.125                    
Increase of system voltage by more than 5 %    Impulse voltage test (MST 14)    61730    1    1    1    1    8    0.125                    
Increase of system voltage by more than 5 %    Sequence B    61730                0                    
Change in cell fixing or internal insulation tape    Humidity freeze test (MQT 12)    61215    264    1    1    264    24    11                    
Change in label material (external nameplate label)    Sequence B    61730                0                (omitting the UV test for the side of the module which does not have the label) on either a full sized module, or to a coupon with similar rigidity as the full sized module and with the same material layer to which the label is affixed    
Change in label material (external nameplate label)    Durability of Markings (MST 05)    61730    1    1    1    1    8    0.125                    
Change from monofacial to bifacial module    UV preconditioning test (MQT 10)    61215    96    1    1    96    24    4                Only for change in cell where 4.2.3 doesn’t already apply    
Change from monofacial to bifacial module    Cyclic (dynamic) mechanical load test (MQT 20)    61215    3    1    1    3    8    0.375                Only for change in cell where 4.2.3 doesn’t already apply    
Change from monofacial to bifacial module    Thermal cycling test, 50 cycles (MQT 11)    61215    264    1    1    264    24    11                Only for change in cell where 4.2.3 doesn’t already apply    
Change from monofacial to bifacial module    Humidity freeze test (MQT 12)    61215    264    1    1    264    24    11                Only for change in cell where 4.2.3 doesn’t already apply    
Change from monofacial to bifacial module    Thermal cycling test, 200 cycles (MQT 11)    61215    720    1    1    720    24    30                    
Change from monofacial to bifacial module    Measurement of temperature coefficients (MQT 04)    61215    12    1    1    12    8    1.5                    
Change from monofacial to bifacial module    Performance at low irradiance (MQT 07)    61215    1    1    1    1    8    0.125                    
Change from monofacial to bifacial module    Hot-spot endurance test (MQT 09)    61215    48    1    1    48    12    4                    
Change from monofacial to bifacial module    Bypass diode thermal test (MQT 18.1)    61215    12    1    1    12    8    1.5                    
Change from monofacial to bifacial module    Potential-induced degradation (MQT 21)    61215    96    1    1    96    24    4                Only for designs incorporating a glass backsheet    
Change from monofacial to bifacial module    Reverse current overload (MST 26)    61730    4    1    1    4    8    0.5                    
Change from monofacial to bifacial module    Continuity of equipotential bonding (MST 13)    61730    1    1    1    1    8    0.125                    
Changes to module operating temperature    repeat the test sequences that contain modified temperatures as detailed in IEC TS 63126                        0                    
Changes affecting system compatibility with variants of the same model                        0
"""

# ----------------------------
# Helpers
# ----------------------------
def load_from_tsv(tsv_text: str) -> pd.DataFrame:
    df = pd.read_csv(StringIO(tsv_text), sep="\t", dtype=str)
    return df

def load_from_file(uploaded) -> pd.DataFrame:
    if uploaded.name.lower().endswith(".csv") or uploaded.name.lower().endswith(".tsv"):
        sep = "\t" if uploaded.name.lower().endswith(".tsv") else ","
        return pd.read_csv(uploaded, sep=sep, dtype=str)
    else:
        # Excel
        return pd.read_excel(uploaded, engine="openpyxl", dtype=str)

def coerce_numeric(s):
    if s is None:
        return np.nan
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(",", "")
    if s in ["", "#DIV/0!", "NaN", "nan", "None"]:
        return np.nan
    try:
        return float(s)
    except Exception:
        return np.nan

def compute_fields(df: pd.DataFrame, use_row_operational: bool, default_operational_hours: float,
                   cost_basis: str, currency: str, overhead: float):
    # Ensure required numeric columns exist
    for col in ["Time (hrs) per one module", "Frequency", "Quantity", "Duration in Hours",
                "Operational Time", "Duration in days", "Cost per test", "Total Cost"]:
        if col not in df.columns:
            df[col] = np.nan

    # Coerce numerics
    for col in ["Time (hrs) per one module", "Frequency", "Quantity",
                "Duration in Hours", "Operational Time", "Duration in days",
                "Cost per test", "Total Cost"]:
        df[col] = df[col].apply(coerce_numeric)

    # Compute Duration in Hours if missing or to normalize:
    # Formula: time_per_module * frequency * quantity
    time_per = df["Time (hrs) per one module"].fillna(0.0)
    freq = df["Frequency"].fillna(0.0)
    qty = df["Quantity"].fillna(0.0)

    df["Duration in Hours"] = time_per * freq * qty

    # Operational hours per day: use per-row if present and flag enabled, else the sidebar default
    if use_row_operational:
        op = df["Operational Time"].where(~df["Operational Time"].isna(), default_operational_hours)
    else:
        op = default_operational_hours

    # Avoid divide-by-zero
    op = pd.to_numeric(op).replace(0, np.nan)
    df["Operational Time"] = op
    df["Duration in days"] = df["Duration in Hours"] / df["Operational Time"]

    # Cost model
    # cost_basis:
    #   - "Per module test": total_cost = cost_per_test * quantity * frequency
    #   - "Per batch occurrence": total_cost = cost_per_test * frequency
    #   - "Per test line item": total_cost = cost_per_test (as-is)
    cpt = df["Cost per test"].fillna(0.0)
    if cost_basis == "Per module test":
        total = cpt * df["Quantity"].fillna(0.0) * df["Frequency"].fillna(0.0)
    elif cost_basis == "Per batch occurrence":
        total = cpt * df["Frequency"].fillna(0.0)
    else:
        total = cpt

    # Overhead multiplier (e.g., 1.10 for 10% overhead or surcharge)
    df["Total Cost"] = total * float(overhead)

    # Currency formatting friendly column (not used in calculations)
    df["Total Cost (" + currency + ")"] = df["Total Cost"]

    return df

def infer_equipment(test_desc: str) -> str:
    if not isinstance(test_desc, str):
        return ""
    s = test_desc.lower()
    # Lightweight equipment inference
    if "thermal cycling" in s:
        return "Climate chamber (TC)"
    if "humidity freeze" in s:
        return "Climate chamber (HF)"
    if "damp heat" in s:
        return "Damp Heat chamber"
    if "uv preconditioning" in s:
        return "UV chamber"
    if "pid" in s or "potential-induced" in s:
        return "PID setup + HV PSU"
    if "hail" in s:
        return "Hail gun"
    if "static mechanical load" in s:
        return "Static ML rig"
    if "cyclic (dynamic) mechanical load" in s or "mqt 20" in s:
        return "Dynamic ML rig"
    if "wet leakage" in s or "insulation" in s:
        return "HV/IR tester"
    if "hot-spot" in s or "reverse current overload" in s or "bypass diode thermal" in s:
        return "Power supply + IR camera"
    if "visual inspection" in s:
        return "Visual station + light table"
    if "performance at stc" in s or "maximum power determination" in s:
        return "Solar simulator + SMU"
    if "temperature coefficients" in s or "low irradiance" in s:
        return "Solar simulator (variable conditions)"
    if "module breakage" in s:
        return "Impact/Drop apparatus"
    if "screw connections" in s:
        return "Torque tool + fixtures"
    if "materials creep" in s:
        return "Mechanical creep rig"
    if "bending test" in s:
        return "Bending jig"
    return ""

def apply_equipment_inference(df: pd.DataFrame, only_fill_empty=True):
    col = "Equipment, Software required"
    if col not in df.columns:
        df[col] = ""
    if only_fill_empty:
        mask = df[col].isna() | (df[col].astype(str).str.strip() == "")
        df.loc[mask, col] = df.loc[mask, "Test Description"].apply(infer_equipment)
    else:
        df[col] = df["Test Description"].apply(infer_equipment)
    return df

def to_excel_bytes(df: pd.DataFrame) -> BytesIO:
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Retest plan", index=False)
        # Summary sheet
        piv1 = df.pivot_table(
            index="Critical component list", values=["Duration in Hours", "Duration in days", "Total Cost"],
            aggfunc="sum", fill_value=0
        )
        piv1.to_excel(writer, sheet_name="Summary by Component")
        piv2 = df.pivot_table(
            index="Standard", values=["Duration in Hours", "Duration in days", "Total Cost"],
            aggfunc="sum", fill_value=0
        )
        piv2.to_excel(writer, sheet_name="Summary by Standard")
    out.seek(0)
    return out

# ----------------------------
# UI
# ----------------------------
st.title("IEC TS 62915:2023 Retesting Planner + Costing")

with st.expander("Standards reminders (planning context)", expanded=False):
    st.markdown(
        "- **62915:2023** aligns retesting with **IEC 61215:2021** and **IEC 61730:2023**, "
        "including retest considerations for **MQT 20** and **MQT 21**; use the official matrix for final decisions. "
        "(Source: IEC Webstore summary / standard descriptions)  \n"
        "- **Sample counts & pass/fail**: taken from **IEC 61215/61730**; 62915 provides the retest framework/matrix.  \n"
        "- **Electrical terminations**: see **COR1:2024** note pointing to **IEC 61730-2 Clause 6** / **IEC 61215-1 Clause 4**."
    )

with st.sidebar:
    st.header("1) Load data")
    mode = st.radio("Data source", ["Use built-in demo", "Upload CSV/Excel", "Paste TSV/CSV"])

    if mode == "Use built-in demo":
        df_raw = load_from_tsv(DEMO_TSV)
    elif mode == "Upload CSV/Excel":
        up = st.file_uploader("Upload .csv, .tsv or .xlsx", type=["csv", "tsv", "xlsx"])
        if up:
            df_raw = load_from_file(up)
        else:
            df_raw = pd.DataFrame()
    else:
        txt = st.text_area("Paste CSV/TSV data", height=200, value=DEMO_TSV)
        df_raw = load_from_tsv(txt) if txt.strip() else pd.DataFrame()

    st.header("2) Assumptions")
    use_row_operational = st.checkbox("Respect per-row 'Operational Time' if present (else use default below)", True)
    default_operational_hours = st.number_input("Default Operational hours/day", min_value=1.0, max_value=24.0, value=8.0, step=1.0)
    cost_basis = st.selectbox("Cost basis", ["Per module test", "Per batch occurrence", "Per test line item"], index=0)
    currency = st.text_input("Currency (display)", value="₹")
    overhead = st.number_input("Overhead multiplier (e.g., 1.10 for +10%)", min_value=0.0, value=1.00, step=0.05)

    st.header("3) Equipment inference")
    fill_eq = st.checkbox("Auto-fill equipment from test name (leave existing values intact)", True)

# Ensure we have data
if df_raw.empty:
    st.info("Load a dataset from the sidebar to proceed.")
    st.stop()

# Normalize column names for consistent access (strip spaces)
df_raw.columns = [c.strip() for c in df_raw.columns]

# Optional equipment backfill
if fill_eq:
    df_raw = apply_equipment_inference(df_raw, only_fill_empty=True)

# Compute derived fields
df = compute_fields(df_raw.copy(), use_row_operational, default_operational_hours, cost_basis, currency, overhead)

# ----------------------------
# Filters
# ----------------------------
st.subheader("Filters")
cols = st.columns(4)
with cols[0]:
    comp_opts = sorted(df["Critical component list"].dropna().unique().tolist())
    comp_sel = st.multiselect("Critical component list", options=comp_opts, default=[])
with cols[1]:
    std_opts = sorted(df["Standard"].dropna().astype(str).unique().tolist())
    std_sel = st.multiselect("Standard", options=std_opts, default=[])
with cols[2]:
    search = st.text_input("Search (in Test Description / Remarks)", "")
with cols[3]:
    min_hours = st.number_input("Min Duration (hours) filter", min_value=0.0, value=0.0, step=1.0)

mask = pd.Series(True, index=df.index)
if comp_sel:
    mask &= df["Critical component list"].isin(comp_sel)
if std_sel:
    mask &= df["Standard"].astype(str).isin(std_sel)
if search.strip():
    s = search.lower()
    mask &= df["Test Description"].astype(str).str.lower().str.contains(s) | df.get("Remarks", pd.Series("", index=df.index)).astype(str).str.lower().str.contains(s)
mask &= df["Duration in Hours"].fillna(0) >= min_hours

df_view = df[mask].copy()

# ----------------------------
# Editor & KPIs
# ----------------------------
st.subheader("Plan (editable)")
st.caption("Tip: You can edit quantities, frequency, costs, and remarks directly.")
edited = st.data_editor(df_view, use_container_width=True, num_rows="dynamic")

# KPIs
k1, k2, k3 = st.columns(3)
with k1:
    st.metric("Total Duration (hours)", f"{edited['Duration in Hours'].fillna(0).sum():,.1f}")
with k2:
    st.metric("Total Duration (days)", f"{edited['Duration in days'].fillna(0).sum():,.2f}")
with k3:
    st.metric(f"Total Cost ({currency})", f"{edited['Total Cost'].fillna(0).sum():,.2f}")

# Summaries
st.subheader("Summary tables")
c1, c2 = st.columns(2)
with c1:
    st.markdown("**By Critical component list**")
    st.dataframe(
        edited.pivot_table(index="Critical component list", values=["Duration in Hours", "Duration in days", "Total Cost"],
                           aggfunc="sum", fill_value=0).sort_values("Duration in Hours", ascending=False),
        use_container_width=True
    )
with c2:
    st.markdown("**By Standard**")
    st.dataframe(
        edited.pivot_table(index="Standard", values=["Duration in Hours", "Duration in days", "Total Cost"],
                           aggfunc="sum", fill_value=0).sort_values("Duration in Hours", ascending=False),
        use_container_width=True
    )

# ----------------------------
# Export
# ----------------------------
st.subheader("Export")
csv_bytes = edited.to_csv(index=False).encode("utf-8")
st.download_button("Download CSV", data=csv_bytes, file_name="iec62915_retest_plan.csv", mime="text/csv")
xlsx_bytes = to_excel_bytes(edited)
st.download_button("Download Excel (.xlsx)", data=xlsx_bytes, file_name="iec62915_retest_plan.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.markdown("---")
st.markdown(
    "**Note:** This planner provides an engineering judgment starting point. "
    "Confirm final retest sequences & sample counts with the **official IEC TS 62915:2023 matrix** "
    "and apply base standard requirements from **IEC 61215:2021** and **IEC 61730:2023**. "
    "For electrical terminations, review **COR1:2024** and the cross-referenced clauses."
)
