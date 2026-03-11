# Oncology Note mCODE Conversion Prototype (Version 0.1.0)

## Mission
This project aims to validate a prototype system designed to convert unstructured clinical oncology notes into structured, research-grade mCODE (Minimal Common Oncology Data Elements) data, formatted as a FHIR Bundle.

## The Problem
Initial testing has revealed two critical issues with the current prototype:
1.  **Medication Dosage Hallucination:** The system sometimes invents or misrepresents medication dosages that are not accurate to the source text's context.
2.  **Missed Disease Progression:** The system often fails to extract narrative evidence of disease progression, defaulting to a "stable" status.

This validation exercise uses a sample note (`clinical_note.txt`) to diagnose these failures and propose solutions.

---

## System Architecture

The prototype script (`process_note.py`) simulates the "LLM Gateway" component in a larger data pipeline.

**Diagram:**
`[EHR] → [PII Masking] → [LLM Gateway (This Script)] → [Human Review] → [Data Warehouse]`

---

## How to Run

1.  Ensure you have Python 3 installed.
2.  Place `clinical_note.txt` in the same directory as `process_note.py`.
3.  Run the script from your terminal:
    ```bash
    python process_note.py
    ```
4.  The script will generate an `mcode_output.json` file containing the structured FHIR Bundle.

---

## Code Description and Bug Analysis

The script `process_note.py` uses a combination of section parsing and regular expressions to identify and extract key clinical information. It attempts to map this data to simplified mCODE profiles, including `Patient`, `MedicationRequest`, and an `Observation` for disease status.

Upon running the script with `clinical_note.txt`, the following bugs were confirmed:

### Bug 1: Medication Dosage Hallucination

-   **Observation:** The script incorrectly extracts the dosage for **Furosemide as "80 mg"**.
-   **Ground Truth:** The `MEDICATIONS (Prior to Admission)` section clearly lists "Furosemide: 40 mg PO daily".
-   **Root Cause Analysis:** The `extract_medications` function correctly identifies "Furosemide" from the medication list. However, it then performs a naive search across the *entire document* for a dosage pattern following the drug name. It finds the "Furosemide 80 mg IV BID" mentioned in the **`ASSESSMENT & PLAN`** section and incorrectly assigns it, ignoring the original context. This is a critical **context-awareness failure**.

### Bug 2: Missed Disease Progression

-   **Observation:** The system outputs the patient's disease status as **"Patient's condition improved"**.
-   **Ground Truth:** The HPI section explicitly states a "gradual decline in functional status," "worsening abdominal distension," and "increasing ... edema." The correct status should be "Patient's condition worsened."
-   **Root Cause Analysis:** The `extract_disease_status` function uses a simple keyword search. It finds the word "decline" in the HPI, but it continues searching and later finds the phrase "resolves with rest". The flawed logic prioritizes the last keyword found ("resolves"), incorrectly mapping it to an "improving" status. It completely misses the overarching negative sentiment and fails to synthesize the multiple data points indicating progression.

---

## Discussion Points for System Improvement

### 1. Input Guardrail: Where to catch PII?

-   **Problem:** The raw note contains PII (Name, DOB, MRN). Feeding this to an external LLM Gateway (like a public API) is a major compliance and privacy risk.
-   **Solution:** PII masking must happen **before** the data leaves the trusted environment. The ideal location is in the **`[PII Masking]`** service, immediately after export from the EHR. This service would replace names with placeholders (e.g., `[PATIENT_NAME]`), dates with offsets, and remove identifiers.
-   **Why:** This approach minimizes the "attack surface" for PII exposure, reduces the compliance burden on the LLM Gateway, and can lower costs, as processing PII often requires more expensive, specially compliant infrastructure.

### 2. Human-in-the-loop Node: Who signs off?

-   **Problem:** Given the system's demonstrated unreliability (hallucinations, missed context), its output cannot be trusted for research-grade data without verification.
-   **Solution:** A **`[Human Review]`** step is essential. The reviewer should be a clinically knowledgeable individual, such as a **Clinical Research Coordinator**, **Oncology Nurse Navigator**, or a trained **Clinical Data Abstractor**.
-   **Workflow:** The review interface should present the original text side-by-side with the extracted data. The system should also provide confidence scores for each extraction, flagging low-confidence items (e.g., complex medication instructions, ambiguous statements) for mandatory review. The human's sign-off creates the final, validated record for the data warehouse.

### 3. Fallback: If the LLM Gateway goes down, what happens?

-   **Problem:** A real-time data pipeline is brittle if a key component, like a third-party API, becomes unavailable.
-   **Solution:** The system needs a **persistent message queue** (e.g., RabbitMQ, AWS SQS, Google Pub/Sub) placed **before** the `[LLM Gateway]`.
-   **Workflow:**
    1.  The `[PII Masking]` service places the masked clinical note into the queue as a message.
    2.  The `[LLM Gateway]` service pulls messages from this queue for processing.
    3.  If the gateway is down or returns an error (e.g., 503 Service Unavailable), the message is **not acknowledged** and remains in the queue. The system should be configured to retry processing with an exponential backoff strategy.
-   **Benefit:** This ensures **durability and resilience**. No data is lost during an outage; it simply waits in the queue until the service is restored.