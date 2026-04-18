import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Initialize Supabase Client
# Using service_role key is recommended for backend tools to bypass RLS 
# but anon_key works if policies are set as we discussed.
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
# --- TOOLS (Database Actions) ---


def _normalize_days(value, default=7, minimum=1, maximum=90):
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = default

    if days < minimum:
        return minimum
    if days > maximum:
        return maximum
    return days


def _normalize_med_name(value):
    if not isinstance(value, str):
        return ""
    return value.strip()[:80]

def get_medication_info(patient_id: str, **kwargs):
    """Fetches all current medications for the patient."""
    try:
        response = supabase.table("medications") \
            .select("id, med_name, dosage, start_date, end_date") \
            .eq("profile_id", patient_id) \
            .order("created_at", desc=True) \
            .execute()
        return response.data
    except Exception as e:
        print(f"Error fetching medications: {e}")
        return []

def get_adherence_history(patient_id: str, days: int = 7, **kwargs):
    """Fetches general adherence history."""
    try:
        days = _normalize_days(days)
        date_limit = (datetime.now() - timedelta(days=days)).isoformat()
        response = supabase.table("adherence_logs") \
            .select("status, scheduled_time, responded_at, reminders(reminder_time), medications(med_name, dosage)") \
            .eq("profile_id", patient_id) \
            .gte("scheduled_time", date_limit) \
            .order("scheduled_time", desc=True) \
            .limit(100) \
            .execute()
        return response.data
    except Exception as e:
        print(f"Error fetching adherence: {e}")
        return []

def check_med_status(patient_id: str, med_name: str, days: int = 7, **kwargs):
    """
    Search adherence for a specific medicine name.
    Matches the 'check_med_status' tool the AI likes to call.
    """
    try:
        days = _normalize_days(days)
        med_name = _normalize_med_name(med_name)
        if not med_name:
            return []

        date_limit = (datetime.now() - timedelta(days=days)).isoformat()
        response = supabase.table("adherence_logs") \
            .select("status, scheduled_time, responded_at, medications!inner(med_name, dosage)") \
            .eq("profile_id", patient_id) \
            .ilike("medications.med_name", f"%{med_name}%") \
            .gte("scheduled_time", date_limit) \
            .order("scheduled_time", desc=True) \
            .limit(50) \
            .execute()
        return response.data
    except Exception as e:
        print(f"Error in specific med check: {e}")
        return []

def get_specific_reminder_times(patient_id: str, med_name: str, **kwargs):
    """Finds what times a specific medicine is scheduled."""
    try:
        med_name = _normalize_med_name(med_name)
        if not med_name:
            return []

        response = supabase.table("reminders") \
            .select("id, reminder_time, medications!inner(med_name, dosage)") \
            .eq("medications.profile_id", patient_id) \
            .ilike("medications.med_name", f"%{med_name}%") \
            .order("reminder_time", desc=False) \
            .execute()
        return response.data
    except Exception as e:
        print(f"Error fetching specific reminders: {e}")
        return []


def get_health_snapshot(patient_id: str, days: int = 7, **kwargs):
    """
    Returns a compact personalized summary payload to answer broad user-specific questions.
    """
    days = _normalize_days(days)

    medications = get_medication_info(patient_id)
    adherence = get_adherence_history(patient_id, days=days)

    reminder_count = 0
    reminder_preview = []

    try:
        reminders_response = supabase.table("reminders") \
            .select("id, reminder_time, medications(med_name)") \
            .eq("medications.profile_id", patient_id) \
            .order("reminder_time", desc=False) \
            .execute()

        reminders = reminders_response.data or []
        reminder_count = len(reminders)
        reminder_preview = reminders[:10]
    except Exception as e:
        print(f"Error fetching reminder snapshot: {e}")

    return {
        "summary_type": "health_snapshot",
        "window_days": days,
        "medications": medications,
        "adherence": adherence,
        "reminder_count": reminder_count,
        "reminder_preview": reminder_preview,
    }


TOOL_SPECS = {
    "query_medications": {"requires": [], "optional": []},
    "query_adherence": {"requires": [], "optional": ["days"]},
    "query_reminders": {"requires": ["med_name"], "optional": []},
    "check_med_status": {"requires": ["med_name"], "optional": ["days"]},
    "query_health_snapshot": {"requires": [], "optional": ["days"]},
}


def sanitize_tool_parameters(tool_name: str, params: dict):
    if not isinstance(params, dict):
        params = {}

    safe = {}

    if tool_name in {"query_adherence", "check_med_status", "query_health_snapshot"}:
        safe["days"] = _normalize_days(params.get("days", 7))

    if tool_name in {"query_reminders", "check_med_status"}:
        med_name = _normalize_med_name(params.get("med_name", ""))
        if med_name:
            safe["med_name"] = med_name

    return safe


def validate_tool_parameters(tool_name: str, params: dict):
    spec = TOOL_SPECS.get(tool_name)
    if not spec:
        return False, "Unknown tool."

    for required_key in spec["requires"]:
        value = params.get(required_key)
        if not value:
            return False, f"Missing required parameter: {required_key}."

    return True, ""

# Unified Tool Mapping
AVAILABLE_TOOLS = {
    "query_medications": get_medication_info,
    "query_adherence": get_adherence_history,
    "query_reminders": get_specific_reminder_times,
    "check_med_status": check_med_status,
    "query_health_snapshot": get_health_snapshot,
}