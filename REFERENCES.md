# TPS References

Sources behind the Turn Pattern Sustainability model: why Monte Carlo simulation fits this question, where the analysis methods come from, and how simulation has been used for sortie generation and aircraft maintenance. Each entry notes how TPS uses it. Rule IDs refer to `MODEL_LOGIC.md`.

## 1. Why Monte Carlo simulation fits this question

Whether a turn pattern holds up depends on many chance events that interact: breaks, aborts, fix times, spares running out, and aircraft coming back in time for a turn. There is no simple formula for that, which is the classic case for Monte Carlo simulation: play the week out thousands of times with the random events drawn from the unit's own rates, and count how often the plan holds.

**Metropolis, N., and S. Ulam (1949).** "The Monte Carlo Method." *Journal of the American Statistical Association* 44(247): 335–341.
The first published description of the method: estimating outcomes of complex chance processes by repeated random sampling. *TPS:* the core approach, simulating each week many times (rules A-1, X-2).

**Law, A. M. (2015).** *Simulation Modeling and Analysis*, 5th ed. McGraw-Hill Education.
Standard text on building, verifying, and analyzing simulation models. Covers output analysis, comparing alternatives, variance reduction (including common random numbers), and sensitivity analysis. *TPS:* comparing fixes and patterns on the same seed is the common random numbers technique (L-1, P-6); replication-based estimates (M-4).

## 2. Analysis methods

**Wilson, E. B. (1927).** "Probable Inference, the Law of Succession, and Statistical Inference." *Journal of the American Statistical Association* 22: 209–212.
**Agresti, A., and B. A. Coull (1998).** "Approximate Is Better than 'Exact' for Interval Estimation of Binomial Proportions." *The American Statistician* 52(2): 119–126. doi:10.1080/00031305.1998.10480550
Wilson's score interval for a success rate, and the comparison showing it keeps close to its stated confidence level, unlike the simple normal-approximation interval. *TPS:* the 95% range on every success rate (M-4).

**Saltelli, A., M. Ratto, T. Andres, F. Campolongo, J. Cariboni, D. Gatelli, M. Saisana, and S. Tarantola (2008).** *Global Sensitivity Analysis: The Primer.* John Wiley & Sons. doi:10.1002/9780470725184
Practical guide to sensitivity analysis: finding which inputs drive a model's answer, and making model-based conclusions defensible. *TPS:* basis for the planned sensitivity, break-even, and input-uncertainty analyses.

## 3. Verification and validation

**Sargent, R. G. (2013).** "Verification and Validation of Simulation Models." *Journal of Simulation* 7(1): 12–24.
Defines conceptual model validity, model verification, operational validity, and data validity, and recommends a validation procedure. *TPS:* the readable reference engine checked against the fast engine (A-3), rule-by-rule tests tied to `MODEL_LOGIC.md` (verification), and planned backtesting against real weeks (operational validity).

**U.S. Department of Defense (2024).** DoD Instruction 5000.61, *DoD Modeling and Simulation Verification, Validation, and Accreditation*, September 17, 2024.
DoD policy that models and simulations supporting DoD decisions undergo verification and validation throughout their life cycles and are accredited for their intended use. *TPS:* the standard to work toward if TPS results are used formally. Run records, fingerprints, and the logic document (A-1) are the kind of documentation accreditation draws on.

## 4. Simulation in sortie generation and aircraft maintenance

**Fisher, R. R., W. W. Drake, J. J. Delfausse, A. J. Clark, and A. Buchanan (1968).** *The Logistics Composite Model: An Overall View.* RAND Corporation, RM-5544.
The original description of the Logistics Composite Model (LCOM), developed by RAND and Air Force Logistics Command. It simulates flying, servicing, malfunctions, flight-line maintenance, and repair at an Air Force base. *TPS:* precedent for simulating sortie generation as chance events on a timeline; TPS is a much lighter, planning-focused cousin.

**Air Force Human Resources Laboratory (1990).** *LCOM Explained.* AFHRL-TP-90-58. DTIC ADA224497.
A general-audience explanation of LCOM: a simulation of an aircraft maintenance organization, used to derive maintenance manpower requirements. *TPS:* shows simulation has long been accepted in Air Force maintenance decisions.

**Harris, J. W., Jr. (2002).** "The Sortie Generation Rate Model." In *Proceedings of the 2002 Winter Simulation Conference*, ed. E. Yücesan, C.-H. Chen, J. L. Snowdon, and J. M. Charnes. Air Force Studies and Analyses Agency.
A light simulation of sortie generation built as a commander's planning tool, needing little input data. It reports utilization as cumulative sorties per aircraft, models ground aborts and turns, validates against an LCOM-based study, and runs sensitivity tests. *TPS:* closest precedent for TPS's purpose (quick planning answers from operational inputs) and its utilization measures (M-7, M-9).

**"Feasibility Study of Variance Reduction in the Logistics Composite Model" (2007).** In *Proceedings of the 2007 Winter Simulation Conference*. Air Force Institute of Technology.
Examines variance-reduction techniques in LCOM, a stochastic simulation the Air Force uses to set maintenance manpower. *TPS:* support for running alternatives on common random numbers so comparisons are fair (L-1, P-6).

**Mattila, V., K. Virtanen, and T. Raivio (2008).** "Improving Maintenance Decision Making in the Finnish Air Force Through Simulation." *Interfaces* 38(3): 187–201. doi:10.1287/inte.1080.0349
Discrete-event simulation of fighter aircraft maintenance, built as a stand-alone tool for maintenance planners to study how resources, policies, and operating conditions affect aircraft availability. *TPS:* close precedent for a maintenance-planner tool; also notes the challenge of scarce and sensitive data, which TPS handles by keeping unit data local.

**Mattila, V., and K. Virtanen (2014).** "Maintenance Scheduling of a Fleet of Fighter Aircraft through Multi-Objective Simulation-Optimization." *Simulation* 90(9): 1023–1040.
Combines fighter fleet simulation with a search for schedules that are best across several objectives at once, then helps a decision-maker choose among them. *TPS:* precedent for the pattern search (P-1 to P-6) and for a planned efficient frontier that trades sorties, success, and resources.

## 5. Commercial aviation: airline operations, turnarounds, and maintenance

Airlines and researchers outside defense use the same tools for the same kind of question: how a plan holds up when chance disruptions hit, and where slack or resources do the most good.

**Rosenberger, J. M., A. J. Schaefer, D. Goldsman, E. L. Johnson, A. J. Kleywegt, and G. L. Nemhauser (2002).** "A Stochastic Model of Airline Operations." *Transportation Science* 36(4): 357–377.
SimAir, a simulation of a domestic airline's daily operations used to evaluate plans and recovery policies under random disruptions. *TPS:* the same idea of judging a plan by how it performs across many simulated days, including how recovery choices (here spares and 2407 adds) change the outcome.

**Lan, S., J.-P. Clarke, and C. Barnhart (2006).** "Planning for Robust Airline Operations: Optimizing Aircraft Routings and Flight Departure Times to Minimize Passenger Disruptions." *Transportation Science* 40(1): 15–28.
Reduces delay propagation by routing aircraft and retiming flights so slack sits where delays are likely. *TPS:* the logic behind testing pattern shapes and fixes, where the same total flying can be far more robust when the schedule's slack is placed well (P-3, L-1).

**Wu, C.-L. (2005).** "Inherent Delays and Operational Reliability of Airline Schedules." *Journal of Air Transport Management* 11(4): 273–282.
Uses simulation to separate the delays built into a schedule by thin buffers from those caused by disruptions, and finds schedules must account for day-to-day randomness. *TPS:* why a plan that works on paper can still fail most weeks.

**Wu, C.-L., and R. E. Caves (2004).** "Modelling and Simulation of Aircraft Turnaround Operations at Airports." *Transportation Planning and Technology* 27(1): 25–46.
A Monte Carlo turnaround model compared with three months of an airline's flight data; on-time performance depends on the buffer built into ground time and on how efficiently the turnaround runs. *TPS:* closest commercial parallel to turn windows and fix times (T-2, F-1), and an example of validating a turnaround simulation against real data.

**San Antonio, A., A. A. Juan, L. Calvet, P. Fonseca i Casas, and D. Guimarans (2017).** "Using Simulation to Estimate Critical Paths and Survival Functions in Aircraft Turnaround Processes." In *Proceedings of the 2017 Winter Simulation Conference*, 3394–3403. doi:10.1109/WSC.2017.8248055
Monte Carlo simulation of a Boeing 737-800 turnaround with random task times, giving the probability the turnaround finishes by each target time. *TPS:* the same idea as cumulative fix windows, the share of aircraft ready within each number of hours (F-1).

**Bazargan-Lari, M., P. Gupta, and S. Young (2003).** "A Simulation Approach to Manpower Planning." In *Proceedings of the 2003 Winter Simulation Conference*.
A line maintenance simulation for Continental Airlines at Newark, checked against actual staffing, with sensitivity analysis and a search for better shift schedules. *TPS:* precedent for simulating maintenance shift coverage (F-4) and for validating against real numbers.

**Shahmoradi-Moghadam, H., N. Safaei, and S. J. Sadjadi (2021).** "Robust Maintenance Scheduling of Aircraft Fleet: A Hybrid Simulation-Optimization Approach." *IEEE Access*. doi:10.1109/ACCESS.2021.3053714
Schedules fleet maintenance so enough aircraft are ready for planned missions, using Monte Carlo sampling of uncertain repair times. *TPS:* support for treating fix times as uncertain and judging a plan by whether enough aircraft are ready when needed.

## 6. Planning guidance

**Department of the Air Force.** DAFI 21-101, *Aircraft and Equipment Maintenance Management* (with Change 1).
Public maintenance management guidance. Paragraphs referenced in `MODEL_LOGIC.md` section 12 include 1.3.3 (utilization standards and standard turn patterns), 1.14 (duty limits), Table 1.2 (repair priorities), 2.4.3.15 (repeat/recur procedures), and 2.9.9.2 (use of a sortie production model). *TPS:* grounds the rules tagged DAFI 21-101.

---

*Restricted publications are not used or cited. Planning values in TPS are always the unit's own inputs.*
