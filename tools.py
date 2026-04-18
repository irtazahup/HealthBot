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

def get_medication_info(patient_id: str, **kwargs):
    """Fetches all current medications for the patient."""
    try:
        response = supabase.table("medications").select("*").eq("profile_id", patient_id).execute()
        return response.data
    except Exception as e:
        print(f"Error fetching medications: {e}")
        return []

def get_adherence_history(patient_id: str, days: int = 7, **kwargs):
    """Fetches adherence logs for a specific number of days."""
    try:
        # Calculate the date limit
        date_limit = (datetime.now() - timedelta(days=days)).isoformat()
        
        # Query logs joined with reminders to see the scheduled times
        response = supabase.table("adherence_logs") \
            .select("status, scheduled_time, responded_at, reminders(reminder_time)") \
            .eq("profile_id", patient_id) \
            .gte("scheduled_time", date_limit) \
            .order("scheduled_time", desc=True) \
            .execute()
        
        return response.data
    except Exception as e:
        print(f"Error fetching adherence: {e}")
        return []

def get_specific_reminder_times(patient_id: str, med_name: str, **kwargs):
    """Finds what times a specific medicine is scheduled using a join."""
    try:
        # Use !inner to filter the medications table within the join
        response = supabase.table("reminders") \
            .select("id, reminder_time, medications!inner(med_name, dosage)") \
            .eq("medications.profile_id", patient_id) \
            .ilike("medications.med_name", f"%{med_name}%") \
            .execute()
            
        return response.data
    except Exception as e:
        print(f"Error fetching specific reminders: {e}")
        return []

# Mapping dictionary for the AI Agent to identify which function to run
AVAILABLE_TOOLS = {
    "query_medications": get_medication_info,
    "query_adherence": get_adherence_history,
    "query_reminders": get_specific_reminder_times
}