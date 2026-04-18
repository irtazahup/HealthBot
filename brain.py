import os
import json
from groq import Groq
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SUPPORTED_TOOLS = {
  "query_medications",
  "query_adherence",
  "query_reminders",
  "check_med_status",
  "query_health_snapshot",
}


def _trim_history(chat_history, max_items=8):
  if not chat_history:
    return []
  return chat_history[-max_items:]


def _safe_parse_json(raw_text):
  if not raw_text:
    return {}

  try:
    return json.loads(raw_text)
  except json.JSONDecodeError:
    # Best-effort recovery for models that wrap JSON in extra text.
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
      try:
        return json.loads(raw_text[start : end + 1])
      except json.JSONDecodeError:
        return {}
    return {}


def _normalize_decision(decision):
  if not isinstance(decision, dict):
    return {"action": "chat"}

  action = str(decision.get("action", "chat")).strip().lower()
  if action not in {"call_tool", "chat"}:
    action = "chat"

  normalized = {"action": action}

  if action == "call_tool":
    tool_name = str(decision.get("tool_name", "")).strip()
    if tool_name not in SUPPORTED_TOOLS:
      return {"action": "chat"}

    parameters = decision.get("parameters", {})
    if not isinstance(parameters, dict):
      parameters = {}

    normalized["tool_name"] = tool_name
    normalized["parameters"] = parameters
    return normalized

  if "reply" in decision and isinstance(decision["reply"], str):
    normalized["reply"] = decision["reply"].strip()

  return normalized

def get_ai_decision(user_text, patient_name, chat_history):
    """
    Phase 1: Decision Making. 
    Determines if we need to call a tool or just reply.
    """
    trimmed_history = _trim_history(chat_history)
    history_str = "\n".join([f"{h['role']}: {h['content']}" for h in trimmed_history])
    today = datetime.now().strftime("%Y-%m-%d")

    system_prompt = f"""
    You are 'MedCompanion Dispatcher'. Today's date is {today}.
    Patient context: {patient_name}

    Your only job is deciding whether to call one data tool or do normal chat.

    AVAILABLE TOOLS:
    - query_medications: list active medications.
    - query_adherence: adherence logs (supports optional days integer).
    - query_reminders: reminder times for a named med (requires med_name).
    - check_med_status: recent status for one medication (requires med_name, optional days).
    - query_health_snapshot: compact summary of meds + reminders + adherence.

    DECISION RULES:
    1. Use call_tool when the user asks anything about their personal meds, doses, reminders, adherence, or "my records".
    2. Use chat for greetings, gratitude, small talk, and general medical education not requiring personal records.
    3. If unsure but wording mentions "my", "I took", "my medicine", prefer call_tool.

    JSON OUTPUT CONTRACT (strict):
    - Either {{"action":"call_tool","tool_name":"...","parameters":{{...}}}}
    - Or {{"action":"chat"}}

    RECENT CHAT HISTORY:
    {history_str}
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
        content = completion.choices[0].message.content
        parsed = _safe_parse_json(content)
        return _normalize_decision(parsed)
    except Exception as e:
        print(f"Decision Phase Error: {e}")
        return {"action": "chat"}


def get_general_answer(user_text, patient_name, chat_history):
    """
    Handles non-tool conversational and general medical queries.
    """
    trimmed_history = _trim_history(chat_history)
    history_str = "\n".join([f"{h['role']}: {h['content']}" for h in trimmed_history])

    system_prompt = f"""
     You are 'MedCompanion', a careful and empathetic health assistant for {patient_name}.

     SCOPE GUARDRAILS (strict):
     1. Stay within medical and health-support context only.
     2. For non-medical requests (celebrity facts, entertainment, politics, coding, etc), politely redirect to health topics.
     3. Never add biographical facts about the patient name. The patient name is only an identifier.
     4. If user asks identity-style queries (example: "what is my name"), reply with only: "Your name is {patient_name}."
     5. Provide educational guidance only; do not claim diagnosis.
     6. If user mentions severe chest pain, breathing issues, stroke symptoms, self-harm, overdose,
       or severe allergic reaction, advise emergency services immediately.
     7. Keep answers practical and clear (2-4 short sentences).

     RECENT CHAT HISTORY:
     {history_str}
     """

    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ]
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"General Chat Error: {e}")
        return "I can help with general health guidance and your medication records. Please try your question again."

def get_final_answer(user_text, patient_name, db_data, chat_history):
    """
    Phase 2: Final Synthesis.
    Takes the raw data from your 'tools.py' and formats it for WhatsApp.
    """
    trimmed_history = _trim_history(chat_history)
    history_str = "\n".join([f"{h['role']}: {h['content']}" for h in trimmed_history])
    
    system_prompt = f"""
    You are 'MedCompanion', a helpful health assistant for {patient_name}.
    You have just retrieved the following data from the database:
    {db_data}

    RECENT HISTORY:
    Use recent history to answer naturally and avoid repetition.
    {history_str}
    

    INSTRUCTIONS:
    1. Answer the user's question: "{user_text}" using the retrieved data.
    2. Be concise (max 4 sentences).
    3. If the data is empty, tell the user you couldn't find those specific records.
    4. Be empathetic and professional.
    5. If the user asks for diagnosis or emergency help, provide safety-first guidance and suggest urgent care/emergency when appropriate.
    6. Never add non-medical biography/celebrity facts about names.
    7. If user asks identity-style query, return only the exact patient name with no extra sentence.
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


def enforce_guardrails(user_text, patient_name, draft_reply):
    """
    Final guardrail pass that keeps responses medical and removes identity embellishments.
    """
    if not draft_reply:
      return f"Your name is {patient_name}." if "name" in user_text.lower() else "I can help with medical questions and your medication records."

    system_prompt = f"""
    You are a strict response safety editor for MedCompanion.

    INPUTS:
    - patient_name: {patient_name}
    - user_query: {user_text}
    - draft_reply: {draft_reply}

    EDIT RULES (strict):
    1. Keep responses only in medical/health assistant scope.
    2. Remove non-medical digressions and any celebrity/biographical facts tied to names.
    3. Do not invent patient data.
    4. If user asks identity-style question about their name, output exactly: "Your name is {patient_name}."
    5. Keep concise and natural for WhatsApp.

    Return only the final edited reply text.
    """

    try:
      completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": "Apply the rules and return the final reply."}
        ]
      )
      edited = completion.choices[0].message.content.strip()
      return edited or draft_reply
    except Exception as e:
      print(f"Guardrail Phase Error: {e}")
      return draft_reply