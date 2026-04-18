import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_ai_decision(user_text, patient_name, chat_history):
    """
    Phase 1: Decision Making. 
    Determines if we need to call a tool or just reply.
    """
    history_str = "\n".join([f"{h['role']}: {h['content']}" for h in chat_history])
    
    system_prompt = f"""
    You are the 'MedCompanion' Dispatcher for patient {patient_name}.
    Your goal is to decide if you need to query the database to answer the user.

    AVAILABLE TOOLS:
    - query_medications: Use if they ask what meds they are on or general med questions.
    - query_adherence: Use if they ask about progress, missed doses, or "how am I doing". Requires 'days' parameter.
    - query_reminders: Use if they ask "when" they should take a specific med. Requires 'med_name' parameter.

    RESPONSE FORMAT:
    You must respond ONLY with a JSON object.
    
    Example for data request:
    {{"action": "call_tool", "tool_name": "query_adherence", "parameters": {{"days": 7}}}}

    Example for simple chat:
    {{"action": "chat", "reply": "Hello! How can I help you today?"}}
    
    RECENT HISTORY:
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