import re
import json
import os
from datetime import datetime

# --- Configuration & Constants ---

# Simulating mCODE value sets for disease status. A real system would use a terminology server.
DISEASE_STATUS_MAPPING = {
    "worsening": {"code": "271299001", "display": "Patient's condition worsened"},
    "progressing": {"code": "271299001", "display": "Patient's condition worsened"},
    "decline": {"code": "271299001", "display": "Patient's condition worsened"},
    "stable": {"code": "359746009", "display": "Patient's condition stable"},
    "improving": {"code": "268910001", "display": "Patient's condition improved"},
    "responding": {"code": "268910001", "display": "Patient's condition improved"},
    "resolves": {"code": "268910001", "display": "Patient's condition improved"}, # A potential source of error
}
DEFAULT_DISEASE_STATUS = {"code": "359746009", "display": "Patient's condition stable"}

# --- Helper Functions ---

def read_note(file_path: str) -> str:
    """Reads the entire content of the clinical note."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
        return ""

def parse_section(note_text: str, section_title: str) -> str:
    """
    A simple parser to extract a specific section from the note.
    This is intentionally basic and might fail on complex note structures.
    """
    try:
        # Regex to find a section title and capture everything until the next section title or end of file
        pattern = re.compile(rf'^\*\*{section_title}:\*\*$(.*?)(?=\n^\*\*|\Z)', re.MULTILINE | re.DOTALL)
        match = pattern.search(note_text)
        if match:
            return match.group(1).strip()
    except Exception as e:
        print(f"Warning: Could not parse section '{section_title}'. Error: {e}")
    return ""

# --- Core Extraction Logic ---

def extract_patient_info(note_text: str) -> dict:
    """Extracts basic patient demographics based on mCODE CancerPatient Profile."""
    patient_info = {}
    
    # Using regex to find key-value pairs. A robust solution would be more flexible.
    name_match = re.search(r"Patient Name:\s*(.*)", note_text)
    mrn_match = re.search(r"MRN:\s*(\d+)", note_text)
    dob_match = re.search(r"DOB:\s*(\d{2}/\d{2}/\d{4})", note_text)

    if name_match:
        patient_info['name'] = name_match.group(1).strip()
    if mrn_match:
        patient_info['mrn'] = mrn_match.group(1).strip()
    if dob_match:
        # Convert to FHIR date format
        dob = datetime.strptime(dob_match.group(1).strip(), "%m/%d/%Y")
        patient_info['dob'] = dob.strftime("%Y-%m-%d")
        
    return patient_info

def extract_medications(note_text: str) -> list:
    """
    Extracts medications and dosages.
    
    *** INTENTIONAL FLAW ***
    This function has a critical logic error. It first finds medication names from the
    'MEDICATIONS' section, but then it searches the ENTIRE document for the first dosage
    value associated with that name. This can lead it to pick up dosages from the
    'ASSESSMENT & PLAN' section, causing a hallucination.
    """
    medications_list = []
    meds_section_text = parse_section(note_text, "MEDICATIONS \(Prior to Admission\)")
    
    if not meds_section_text:
        return medications_list

    # Regex to find medication names from the list format "1. **Medication Name**:"
    med_name_pattern = re.compile(r"\d+\.\s*\*\*(.*?)\s*\(", re.MULTILINE)
    med_names = med_name_pattern.findall(meds_section_text)

    for name in med_names:
        # FLAW: Search the *entire* note for the dosage, not just the line in the med section.
        # This will find "80 mg" for Furosemide in the A&P section first.
        dosage_pattern = re.compile(rf"{re.escape(name)}.*?\b(\d+(\.\d+)?\s*mg)\b", re.IGNORECASE | re.DOTALL)
        dosage_match = dosage_pattern.search(note_text)
        
        dosage_text = dosage_match.group(1) if dosage_match else "Dosage Not Found"
        
        medications_list.append({
            "name": name,
            "dosage": dosage_text
        })
        
    return medications_list

def extract_disease_status(note_text: str) -> dict:
    """
    Extracts the disease status based on keywords.

    *** INTENTIONAL FLAW ***
    This function is too simplistic. It looks for the last keyword related to progression
    or stability in the HPI. In the provided note, it will find "decline" but then later
    find "resolves with rest". The flawed logic will incorrectly prioritize the last
    keyword found ("resolves"), missing the overall context of disease progression.
    """
    hpi_section = parse_section(note_text, "HISTORY OF PRESENT ILLNESS")
    status_keyword_found = None

    if hpi_section:
        # FLAW: Simple keyword search that doesn't understand clinical nuance.
        # It finds multiple keywords and will likely report the last one it finds.
        for keyword in DISEASE_STATUS_MAPPING.keys():
            if re.search(r'\b' + keyword + r'\b', hpi_section, re.IGNORECASE):
                status_keyword_found = keyword # Overwrites previous findings

    if status_keyword_found and status_keyword_found in DISEASE_STATUS_MAPPING:
        # Example: Finds "decline" then "resolves", so it returns "improving".
        return DISEASE_STATUS_MAPPING[status_keyword_found]
    else:
        # If no keywords are found, it defaults to stable, missing the progression.
        return DEFAULT_DISEASE_STATUS

# --- FHIR Bundle Generation ---

def generate_mcode_bundle(patient_info: dict, medications: list, disease_status: dict) -> dict:
    """
    Generates a simplified, FHIR-like mCODE Bundle JSON object.
    This simulates the structure needed for a data lake or registry.
    """
    entries = []

    # 1. Create Patient Resource (mCODE CancerPatient)
    if patient_info:
        patient_resource = {
            "resourceType": "Patient",
            "id": "patient-1",
            "identifier": [{"system": "http://example.hospital/mrn", "value": patient_info.get('mrn')}],
            "name": [{"text": patient_info.get('name')}],
            "birthDate": patient_info.get('dob')
        }
        entries.append({"fullUrl": "urn:uuid:patient-1", "resource": patient_resource})

    # 2. Create MedicationRequest Resources (Cancer-Related Medication Request)
    for i, med in enumerate(medications, 1):
        med_resource = {
            "resourceType": "MedicationRequest",
            "id": f"medreq-{i}",
            "status": "active",
            "intent": "order",
            "subject": {"reference": "Patient/patient-1"},
            "medicationCodeableConcept": {"text": med.get('name')},
            "dosageInstruction": [{"text": med.get('dosage')}]
        }
        entries.append({"fullUrl": f"urn:uuid:medreq-{i}", "resource": med_resource})

    # 3. Create Observation Resource (Cancer Disease Status)
    if disease_status:
        status_resource = {
            "resourceType": "Observation",
            "id": "disease-status-1",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "97509-4"}], "text": "Cancer disease status"},
            "subject": {"reference": "Patient/patient-1"},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": disease_status.get('code'), "display": disease_status.get('display')}]
            }
        }
        entries.append({"fullUrl": "urn:uuid:disease-status-1", "resource": status_resource})

    # Assemble the final bundle
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": datetime.now().isoformat(),
        "entry": entries
    }
    return bundle

# --- Main Execution ---

if __name__ == "__main__":
    note_file = "clinical_note.txt"
    output_file = "mcode_output.json"

    print(f"Processing note: '{note_file}'...")

    # Ensure the note file exists
    if not os.path.exists(note_file):
        print(f"\nFATAL ERROR: The required input file '{note_file}' was not found.")
        print("Please make sure the clinical note is in the same directory as this script.")
    else:
        # Core pipeline
        full_note_text = read_note(note_file)
        
        patient_data = extract_patient_info(full_note_text)
        medication_data = extract_medications(full_note_text)
        status_data = extract_disease_status(full_note_text)
        
        mcode_bundle = generate_mcode_bundle(patient_data, medication_data, status_data)

        # Write output to file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(mcode_bundle, f, indent=2)

        print(f"Processing complete. Output written to '{output_file}'.")
        print("\n--- Validation Summary ---")
        print(f"Extracted Patient: {patient_data.get('name')}")
        print(f"Extracted {len(medication_data)} Medications.")
        print(f"Determined Disease Status: {status_data.get('display')}")
        
        # Highlight the specific problematic extractions for the "student"
        furosemide = next((med for med in medication_data if "Furosemide" in med.get("name", "")), None)
        if furosemide:
            print(f"\n[DEBUG] Furosemide Dosage Extracted: {furosemide.get('dosage')}")