import os
import json
from groq import Groq
from dotenv import load_dotenv
from datetime import datetime
load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_ai_decision(user_text, patient_name, chat_history):
    """
    Phase 1: Decision Making. 
    Determines if we need to call a tool or just reply.
    """
    # history_str = "\n".join([f"{h['role']}: {h['content']}" for h in chat_history])
    today = datetime.now().strftime("%Y-%m-%d")

    system_prompt = f"""
    You are 'MedCompanion Dispatcher'. Today's date is {today}.
    
    Your only job is to decide if you need to query the database for {patient_name}.

    STRATEGY:
    1. Analyze the user's intent.
    2. If they ask about meds, schedules, or adherence, use a TOOL.
    3. If they are just saying hi or thanks, use CHAT.

    EXAMPLES:
    User: "What meds am I taking?"
    Output: {{"thought": "User wants a list of medications.", "action": "call_tool", "tool_name": "query_medications", "parameters": {{}}}}

    User: "Did I miss any doses this week?"
    Output: {{"thought": "User is asking about adherence over 7 days.", "action": "call_tool", "tool_name": "query_adherence", "parameters": {{"days": 7}}}}

    User: "Did I take my Panadol?"
    Output: {{"thought": "Specific med check requested.", "action": "call_tool", "tool_name": "check_med_status", "parameters": {{"med_name": "Panadol", "days": 3}}}}

    RESPONSE FORMAT:
    Respond ONLY with a JSON object.
    
    The Table's scheme of Available Tools are:
    create table public.adherence_logs (
  id uuid not null default extensions.uuid_generate_v4 (),
  profile_id uuid null,
  reminder_id uuid null,
  scheduled_time timestamp with time zone not null,
  status text null default 'pending'::text,
  responded_at timestamp with time zone null,
  medication_id uuid null,
  constraint adherence_logs_pkey primary key (id),
  constraint unique_reminder_per_day unique (reminder_id, scheduled_time),
  constraint adherence_logs_medication_id_fkey foreign KEY (medication_id) references medications (id) on delete CASCADE,
  constraint adherence_logs_profile_id_fkey foreign KEY (profile_id) references profiles (id) on delete CASCADE,
  constraint adherence_logs_reminder_id_fkey foreign KEY (reminder_id) references reminders (id) on delete CASCADE,
  constraint adherence_logs_status_check check (
    (
      status = any (
        array[
          'pending'::text,
          'taken'::text,
          'skipped'::text,
          'missed'::text
        ]
      )
    )
  )
) TABLESPACE pg_default;
create table public.medications (
  id uuid not null default extensions.uuid_generate_v4 (),
  profile_id uuid null,
  med_name text not null,
  dosage text not null,
  start_date date not null,
  end_date date not null,
  created_at timestamp with time zone null default now(),
  constraint medications_pkey primary key (id),
  constraint medications_profile_id_fkey foreign KEY (profile_id) references profiles (id) on delete CASCADE
) TABLESPACE pg_default;
create table public.profiles (
  id uuid not null default extensions.uuid_generate_v4 (),
  attendant_phone text not null,
  patient_phone text not null,
  patient_name text not null,
  timezone text not null,
  created_at timestamp with time zone null default now(),
  constraint profiles_pkey primary key (id)
) TABLESPACE pg_default;
create table public.profiles (
  id uuid not null default extensions.uuid_generate_v4 (),
  attendant_phone text not null,
  patient_phone text not null,
  patient_name text not null,
  timezone text not null,
  created_at timestamp with time zone null default now(),
  constraint profiles_pkey primary key (id)
) TABLESPACE pg_default;
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            response_format={"type": "json_object"} # Forces Groq to return valid JSON
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"Decision Phase Error: {e}")
        return {"action": "chat", "reply": "I'm sorry, I'm having trouble processing that right now."}

def get_final_answer(user_text, patient_name, db_data, chat_history):
    """
    Phase 2: Final Synthesis.
    Takes the raw data from your 'tools.py' and formats it for WhatsApp.
    """
    history_str = "\n".join([f"{h['role']}: {h['content']}" for h in chat_history])
    
    system_prompt = f"""
    You are 'MedCompanion', a helpful health assistant for {patient_name}.
    You have just retrieved the following data from the database:
    {db_data}

    RECENT HISTORY:
    You should use the recent history to asnwer the user's question in a way that is empathetic and easy to understand.
    {history_str}
    

    INSTRUCTIONS:
    1. Answer the user's question: "{user_text}" using the retrieved data.
    2. Be concise (max 3 sentences).
    3. If the data is empty, tell the user you couldn't find those specific records.
    4. Be empathetic and professional.
    """

    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Final Phase Error: {e}")
        return "I found the information, but I'm struggling to summarize it. You have new logs in your record."