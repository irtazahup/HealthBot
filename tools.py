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

def get_medication_info(patient_id: str, **kwargs):
    """Fetches all current medications for the patient."""
    try:
        response = supabase.table("medications").select("*").eq("profile_id", patient_id).execute()
        return response.data
    except Exception as e:
        print(f"Error fetching medications: {e}")
        return []

def get_adherence_history(patient_id: str, days: int = 7, **kwargs):
    """Fetches general adherence history."""
    try:
        date_limit = (datetime.now() - timedelta(days=days)).isoformat()
        response = supabase.table("adherence_logs") \
            .select("status, scheduled_time, responded_at, reminders(reminder_time),reminders(medications(med_name, dosage))") \
            .eq("profile_id", patient_id) \
            .gte("scheduled_time", date_limit) \
            .order("scheduled_time", desc=True) \
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
        date_limit = (datetime.now() - timedelta(days=days)).isoformat()
        # Uses !inner to filter the parent log by the joined medication's name
        response = supabase.table("adherence_logs") \
            .select("status, scheduled_time, medications!inner(med_name)") \
            .eq("profile_id", patient_id) \
            .ilike("medications.med_name", f"%{med_name}%") \
            .gte("scheduled_time", date_limit) \
            .execute()
        return response.data
    except Exception as e:
        print(f"Error in specific med check: {e}")
        return []

def get_specific_reminder_times(patient_id: str, med_name: str, **kwargs):
    """Finds what times a specific medicine is scheduled."""
    try:
        response = supabase.table("reminders") \
            .select("id, reminder_time, medications!inner(med_name, dosage)") \
            .eq("medications.profile_id", patient_id) \
            .ilike("medications.med_name", f"%{med_name}%") \
            .execute()
        return response.data
    except Exception as e:
        print(f"Error fetching specific reminders: {e}")
        return []

# Unified Tool Mapping
AVAILABLE_TOOLS = {
    "query_medications": get_medication_info,
    "query_adherence": get_adherence_history,
    "query_reminders": get_specific_reminder_times,
    "check_med_status": check_med_status  # Added to match AI dispatcher
}