import os
import requests
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

# Import our new brain functions and tools
from brain import get_ai_decision, get_final_answer, get_general_answer, enforce_guardrails
from tools import AVAILABLE_TOOLS, sanitize_tool_parameters, validate_tool_parameters

load_dotenv()

supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


def _format_medication_query_response(tool_name, db_data):
    """
    Deterministic formatter so medication date fields are never dropped by the LLM.
    Returns a string reply when handled, otherwise None.
    """
    if tool_name not in {"query_medications", "query_health_snapshot"}:
        return None

    medications = []
    reminder_preview = []

    if tool_name == "query_medications":
        if isinstance(db_data, list):
            medications = db_data
    elif isinstance(db_data, dict):
        medications = db_data.get("medications") or []
        reminder_preview = db_data.get("reminder_preview") or []

    if not medications:
        return "I could not find any medications in your records right now."

    reminders_by_med = {}
    for item in reminder_preview:
        med_block = item.get("medications") if isinstance(item, dict) else None
        med_name = ""
        if isinstance(med_block, list) and med_block:
            med_name = str(med_block[0].get("med_name", "")).strip()
        elif isinstance(med_block, dict):
            med_name = str(med_block.get("med_name", "")).strip()

        reminder_time = str(item.get("reminder_time", "")).strip() if isinstance(item, dict) else ""
        if med_name and reminder_time:
            reminders_by_med.setdefault(med_name.lower(), []).append(reminder_time)

    lines = ["Here are your medications with dates:"]
    for idx, med in enumerate(medications, start=1):
        med_name = str(med.get("med_name", "Unknown")).strip() if isinstance(med, dict) else "Unknown"
        dosage = str(med.get("dosage", "Not set")).strip() if isinstance(med, dict) else "Not set"
        start_date = str(med.get("start_date", "Not set")).strip() if isinstance(med, dict) else "Not set"
        end_date = str(med.get("end_date", "Not set")).strip() if isinstance(med, dict) else "Not set"

        lines.append(
            f"{idx}. {med_name} ({dosage}) | Start: {start_date} | End: {end_date}"
        )

        times = reminders_by_med.get(med_name.lower(), [])
        if times:
            lines.append(f"   Time(s): {', '.join(times[:3])}")

    return "\n".join(lines)

def send_simple_message(to, text):
    url = f"https://graph.facebook.com/v25.0/{os.getenv('PHONE_NUMBER_ID')}/messages"
    headers = {
        "Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()


def _extract_incoming_message(payload):
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        messages = value.get("messages")
        if not messages:
            return None, None
        return value, messages[0]
    except (KeyError, IndexError, TypeError):
        return None, None

def process_whatsapp_webhook(payload):
    try:
        value, msg = _extract_incoming_message(payload)
        if not msg:
            return

        sender_number = msg.get("from")
        if not sender_number:
            return

        clean_number = sender_number.replace("+", "")

        # 1. Identity Check
        user_profile = supabase.table("profiles").select("*") \
            .or_(f"patient_phone.ilike.%{clean_number}%,attendant_phone.ilike.%{clean_number}%") \
            .execute()

        if not user_profile.data:
            send_simple_message(sender_number, "I don't recognize this number. Please register first!")
            return

        patient_data = user_profile.data[0]
        patient_id = patient_data['id']
        patient_name = patient_data['patient_name']

        # 2. Handle BUTTON CLICKS (Adherence)
        if msg.get("type") == "interactive":
            button_reply = msg['interactive']['button_reply']
            button_id = button_reply['id'] 
            status = "taken" if "taken_" in button_id else "skipped"
            reminder_id = button_id.replace("taken_", "").replace("skipped_", "")
            
            existing_log = supabase.table("adherence_logs").select("*").eq("reminder_id", reminder_id).execute()

            if existing_log.data:
                current_status = existing_log.data[0]['status']
                send_simple_message(sender_number, f"This was already marked as *{current_status}*.")
                return

            supabase.table("adherence_logs").insert({
                "profile_id": patient_id,
                "reminder_id": reminder_id,
                "status": status,
                "scheduled_time": datetime.now().isoformat(),
                "responded_at": datetime.now().isoformat()
            }).execute()

            ack_text = "✅ Great! Stay healthy." if status == "taken" else "⚠️ Noted. Stay safe!"
            send_simple_message(sender_number, ack_text)

        # 3. Handle TEXT MESSAGES (Agentic Flow)
        elif msg.get("type") == "text":
            user_text = msg.get("text", {}).get("body", "").strip()
            if not user_text:
                send_simple_message(sender_number, "I received an empty message. Please type your question.")
                return

            user_text = user_text[:1000]

            # A. Save User Message to Conversations
            supabase.table("conversations").insert({
                "profile_id": patient_id,
                "role": "user",
                "content": user_text
            }).execute()

            # B. Fetch Recent Chat History (Last 5)
            history_query = supabase.table("conversations") \
                .select("role, content") \
                .eq("profile_id", patient_id) \
                .order("created_at", desc=True) \
                .limit(5) \
                .execute()
            chat_history = history_query.data[::-1]

            # C. PHASE 1: Get AI Decision
            decision = get_ai_decision(user_text, patient_name, chat_history)

            final_reply = ""

            if decision.get("action") == "call_tool":
                tool_name = decision.get("tool_name")
                params = sanitize_tool_parameters(tool_name, decision.get("parameters", {}))
                
                # EXECUTION: Call the actual tool from tools.py
                if tool_name in AVAILABLE_TOOLS:
                    valid, reason = validate_tool_parameters(tool_name, params)
                    if valid:
                        try:
                            db_data = AVAILABLE_TOOLS[tool_name](patient_id, **params)

                            # Deterministic medication formatter keeps start/end dates intact.
                            deterministic_reply = _format_medication_query_response(tool_name, db_data)
                            if deterministic_reply:
                                final_reply = deterministic_reply
                            else:
                                # PHASE 2: Final Synthesis with DB Data
                                final_reply = get_final_answer(user_text, patient_name, db_data, chat_history)
                        except Exception as tool_error:
                            print(f"Tool execution failed ({tool_name}): {tool_error}")
                            final_reply = get_general_answer(user_text, patient_name, chat_history)
                    else:
                        final_reply = f"I need a bit more detail to check your records: {reason}"
                else:
                    final_reply = get_general_answer(user_text, patient_name, chat_history)
            
            else:
                # General medical/small-talk path
                final_reply = decision.get("reply") or get_general_answer(user_text, patient_name, chat_history)

            final_reply = enforce_guardrails(user_text, patient_name, final_reply)

            # D. Save Assistant Response & Send
            supabase.table("conversations").insert({
                "profile_id": patient_id,
                "role": "assistant",
                "content": final_reply
            }).execute()
            
            send_simple_message(sender_number, final_reply)

    except Exception as e:
        print(f"Error in background processor: {e}")