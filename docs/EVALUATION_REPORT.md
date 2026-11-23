# Personnel Processing Monitor — Evaluation Report

> **Classification:** Internal working document.
> Contains no raw personnel records, PII, SINQ messages, or complete
> transaction lines. All statistics are aggregate counts derived from
> field slices only.
>
> **Data file evaluated:** `AI_HACK_TEST_TWO.DAT` (operator-supplied,
> gitignored — not included in this repository)
> **Reference file:** `reference-data/sinq_error_reference.txt`
> **Report generated:** 2025 USDA NFC AI Hackathon

---

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Total valid transaction records | **32** |
| Parse errors (malformed lines) | **0** |
| Records with SINQ errors | **32** (100 %) |
| Distinct SINQ error codes | **9** |
| Distinct DOCU_TYPE values | **1** (063) |
| Distinct source systems | **1** (Unknown) |
| Reference lookup coverage | **9 / 9** codes resolved (100 %) |

Every record in this file carries a SINQ error. This is consistent with a
return file that contains only rejected or held transactions — there are no
clean pass-through records in this extract.

---

## 2. Parse Quality

| Check | Result |
|-------|--------|
| Lines read | 32 |
| Lines skipped (blank) | 0 |
| Parse errors (not 200 chars) | **0** |
| Valid records produced | **32** |

**Finding:** The file is structurally clean. Every line is exactly 200
characters. No malformed records were encountered.

---

## 3. Source System Classification

| Source | Records | % of total |
|--------|---------|------------|
| Unknown | 32 | 100 % |
| EmpowHR | 0 | 0 % |
| Employee Personal Page | 0 | 0 % |

**Finding:** No records in this extract carry the `POWRDOCS = "POWRDOCS"` or
`GWEBESS = "GWEBESS"` indicator values. All 32 records are classified as
**Unknown**. This is expected for certain transaction types or agency
configurations where neither indicator is populated. No FESI label is applied
— the source classification rules do not include a FESI identification method.

---

## 4. DOCU_TYPE Distribution

| DOCU_TYPE | Records | % of total |
|-----------|---------|------------|
| 063 | 32 | 100 % |

**Finding:** All records are DOCU_TYPE 063. The reference lookup for this
file uses the **063 → 060 fallback** implemented in `reference.py`: when a
(063, error code) pair has no direct entry in the reference table, the lookup
retries with DOCU_TYPE 060. All 9 error codes in this extract resolve
correctly through this fallback.

---

## 5. SINQ Error Breakdown

Sorted by descending record count, then ascending error code.

| Rank | SINQ Error | Records | % of SINQ | DOCU_TYPE | Approved Description |
|------|-----------|---------|-----------|-----------|----------------------|
| 1 | **507** | 8 | 25.0 % | 063 | POSITION SUPERVISORY CODE MUST BE 2 OR 4 |
| 2 | **006** | 6 | 18.8 % | 063 | AGENCY/SON NOT COMPATIBLE WITH DATA BASE |
| 2 | **605** | 6 | 18.8 % | 063 | PLACING EMPLOYEE IN INACTIVE POSITION ON MASTER |
| 4 | **522** | 5 | 15.6 % | 063 | SCD LV MUST BE PRESENT WITH NAT OF ACTION |
| 5 | **008** | 2 | 6.3 % | 063 | ACCESSION-SALARY RECORD ON DATA BASE |
| 5 | **005** | 2 | 6.3 % | 063 | SSNO NOT FOUND ON DATA BASE |
| 7 | **021** | 1 | 3.1 % | 063 | DOCUMENT BEING HELD FOR MORE THAN ONE AUDIT PASS |
| 7 | **025** | 1 | 3.1 % | 063 | IN SINQ DUE TO ROLLBACK-TAKE APPROPRIATE ACTION |
| 7 | **098** | 1 | 3.1 % | 063 | RESIDENCE ADDRESS MISSING - MUST SUBMIT AD-349 |
| **Total** | | **32** | 100 % | | |

### Key observations

- **507 (25 %)** — Position supervisory code errors are the most frequent.
  These require the submitting office to verify that the supervisory code
  field is set to 2 or 4.

- **006 and 605 (tied at 18.8 % each)** — Agency/SON compatibility and
  inactive position placement errors together account for 37.5 % of all
  SINQ records. Both indicate a mismatch between the transaction data and
  the current state of the NFC master file.

- **522 (15.6 %)** — Service computation date leave (SCD LV) errors
  suggest a pattern of missing or misformatted date fields in this extract.

- **005 (6.3 %)** — Social Security Number not found on the database. These
  may indicate new employees whose records have not yet been established, or
  data-entry errors in the SSN field.

- **025 (3.1 %)** — Rollback-related SINQ. These records were placed in SINQ
  as a result of a system rollback and require manual review of the original
  transaction.

- **098 (3.1 %)** — Missing residence address. These require submission of
  form AD-349 before the transaction can be processed.

---

## 6. Reference Lookup Coverage

| Metric | Value |
|--------|-------|
| Distinct (DOCU_TYPE, error code) pairs in this file | 9 |
| Pairs resolved with an approved description | 9 |
| Pairs returning "No approved reference available" | 0 |
| Lookup method | DOCU_TYPE 063 → fallback to 060 |

**Finding:** 100 % reference coverage for this file. All 9 (063, error code)
pairs were resolved via the 063 → 060 DOCU_TYPE fallback. No sentinel
values appear in the dashboard or CSV export for this extract.

---

## 7. Application Feature Validation

The following dashboard features were verified against this data file:

| Feature | Status | Notes |
|---------|--------|-------|
| Fixed-width parser | ✅ Pass | 32 records parsed, 0 errors |
| 200-character validation | ✅ Pass | All lines exactly 200 chars |
| Source classification | ✅ Pass | Unknown correctly assigned |
| DOCU_TYPE extraction | ✅ Pass | slice `[17:20]` returns `063` |
| SINQ_ERROR extraction | ✅ Pass | 9 distinct codes found |
| Reference lookup (063→060) | ✅ Pass | All 9 codes resolved |
| Dashboard summary cards | ✅ Pass | Counts match raw data |
| Hierarchical breakdown | ✅ Pass | Sorted by count, inner by DOCU_TYPE |
| Filter form | ✅ Pass | Filters narrow results correctly |
| Record detail route | ✅ Pass | Individual records accessible |
| CSV download | ✅ Pass | 8-column export, formula-injection safe |
| Ask box (local fallback) | ✅ Pass | 7 of 8 question patterns answered |
| ParseError exclusion | ✅ Pass | No parse errors; exclusion logic tested synthetically |
| SINQ_MESSAGE not exposed | ✅ Pass | Verified in HTML, CSV, and MCP output |

---

## 8. Test Suite Summary

All automated tests use **synthetic temporary files only** — no operator
`.DAT` files are accessed during testing.

| Test module | Tests | Focus area |
|-------------|-------|------------|
| `test_parser.py` | 43 | Fixed-width parsing, field slices, ParseError handling |
| `test_query.py` | 68 | RecordFilter, ProcessingMonitor, source classification |
| `test_reference.py` | 45 | Reference parser, lookup, 063→060 fallback, sentinel |
| `test_dashboard.py` | 137 | All HTTP routes, CSV, filters, formula injection, pagination |
| `test_find_processing_errors.py` | 41 | MCP tool output, field exclusions |
| `test_ask.py` | 41 | build_context, answer_locally (13 patterns), ask route |
| `test_server.py` | 9 | Server import and tool registration |
| **Total** | **384** | **0 failed** |

**Linter:** Ruff — 0 violations.

---

## 9. Limitations and Open Items

| Item | Detail |
|------|--------|
| Single-file ingestion | The app reads one `.DAT` file at a time. Multi-file or historical comparison is not yet implemented. |
| Source unknown (100 %) | This extract has no EmpowHR or Employee Personal Page indicators. Source breakdown will vary with other files. |
| FESI identification | No documented rule for FESI classification is currently available. Unknown remains the correct label. |
| watsonx.ai | The LLM Ask feature requires an IBM Cloud API key and an associated watsonx.ai Runtime service instance. The local fallback covers 7 of 8 question pattern families without any network call. |
| Authentication | The dashboard is local and read-only. No authentication is implemented. Not suitable for external or production deployment without additional access controls. |

---

## 10. Recommendations

1. **Resolve 507 errors first.** At 25 % of all SINQ records, supervisory
   code errors are the highest-volume item. A bulk review of positions with
   code ≠ 2 and ≠ 4 in the submitting agency's data would reduce this
   category significantly.

2. **Investigate 006 and 605 together.** Both relate to master-file
   compatibility. Coordinating with NFC on current agency/SON mappings and
   active position status may resolve both categories in one correction cycle.

3. **Review 522 date fields.** SCD LV errors often trace to a missing or
   incorrectly formatted date in a specific field on the input transaction.
   Identifying the common transaction type (NOA code) for these 5 records
   would narrow the correction effort.

4. **Confirm 005 SSNs.** Two records have SSNs not found on the database.
   These should be verified against HR source records before resubmission.

5. **Submit AD-349 for 098.** One record is blocked solely by a missing
   residence address. This is a straightforward form submission.

---

*Report prepared by the USDA NFC AI Hackathon team using the Personnel
Processing Monitor — a read-only MCP server and Starlette dashboard built
during the 2025 hackathon. No raw transaction data, SINQ messages, or PII
are included in this document.*
