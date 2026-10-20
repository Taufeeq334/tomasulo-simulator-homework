# Tomasulo Algorithm Implementation

Mohammad Taufeeq Shaik — PS ID 2493846

This is the separate **Tomasulo / O3 simulator assignment**, not the branch predictor homework.

## Run

Python 3.9 or later; standard library only. No compilation or package installation is needed.

```sh
python3 code/main.py tests/arithmetic.in --issue-width 4
python3 code/main.py tests/starter_legacy.in --issue-width 2
python3 run_tests.py
```

The first two commands print instruction ISSUE, EX, MEM, WB and COMMIT cycles, all register values and nonzero memory values. The test command checks twelve testbench files at widths 1–4 and 200 deterministic randomized integer programs against a separate sequential interpreter. It rewrites results/summary.csv, verification.txt and per-test .txt/.json results. Errors raise exceptions and return nonzero exit status. Full timestamps are recorded for every dynamic instruction, including squashed instructions.

`python3 code/main.py` runs the supplied test sequence from code/code.in. `--json output.json` saves full simulator state. `--max-cycles 100000` limits runaway programs. CLI paths with spaces must be quoted.

## Configuration

Use the format from programming-tomasulo.pdf:

```text
Integer adder 4 1 1
FP adder 3 4 1
FP multiplier 2 15 1
Load/store unit 5 1 5 1
ROB entries = 64
Issue width = 2
R1=12, R2=32, F20=3.0
Mem[4]=3.0, Mem[8]=2.0
Addi R3, R1, 4
```

Issue width defaults to 1 and accepts 1–4. The single CDB defaults to one writeback per cycle; commit width defaults to issue width. Optional `Writeback width = N` and `Commit width = N` allow explicit bandwidth experiments. Integer and address units are unpipelined; FP units are pipelined. Memory is nonpipelined and single-ported. R0 is hardwired to zero.

Branches use word offsets by default, following the PDF's `PC + 4 + (offset << 2)`. The starter uses byte offsets instead. `Branch offsets = bytes` explicitly selects that legacy interpretation. tests/starter_legacy.in retains the supplied test_case.txt instruction sequence and adds only that setting. kernel.in uses an authored word-offset loop.

## Files and provenance

- code/: new command-line entry point, refactored cycle engine, default input.
- original/: unchanged supplied tomasulo-python package, with original Qing attribution.
- tests/: supplied legacy testbench and eleven authored testbenches.
- results/: real measured instruction tables, final states, summary CSV, JSON records and verification summary.
- Tomasulo_Assignment_Report.pdf and .docx: formatted report and editable copy; REPORT.md is its text version.
- references/: original assignment and sample report.
- SOURCE_AUDIT.md: requirement mapping, changes, assumptions and known limitations.

The execution core is a substantial rewrite of the supplied starter architecture, rather than a small patch to issue.py. The report explains the replaced routines and why class based state and hard-coded configuration were replaced. Original files remain available for inspection.

## Limits

Loads speculate past unresolved older stores and replay younger instructions if a later store address reveals an alias. Faults are deferred until retirement so wrong-path out-of-range accesses do not abort the program. Memory replay uses a two-cycle restart policy. No instructor timing oracle is available, so timing is validated by structural assertions rather than comparison against the sample's different pipeline policy. The core is a substantial rewrite rather than a minimal starter-code patch; see the report before comparing cycle totals.

## Separate GitHub submission

Create a separate repository, for example `tomasulo-simulator-homework`. Upload the CONTENTS of this folder to its root. Include source, tests, README, report and measured results as required on page 4 of programming-tomasulo.pdf. Submit its URL to the separate Tomasulo assignment if your course requests a URL. Do not place this code in branch-predictor-homework or submit it to the Branch Predictor Homework entry. The supplied documents do not establish this separate assignment's deadline or Teams entry.
