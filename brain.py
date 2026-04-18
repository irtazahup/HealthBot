import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def ask_health_agent(user_text, patient_name, med_data, adherence_data, chat_history):
    """
    med_data: List of meds from Supabase
    adherence_data: List of logs (taken/skipped) from Supabase
    chat_history: Last X messages from conversations table
    """
    
    # Format the data into strings for the prompt
    history_str = "\n".join([f"{h['role']}: {h['content']}" for h in chat_history])
    
    system_prompt = f"""
    You are 'MedCompanion'. 
    Patient: {patient_name}
    
    CURRENT MEDICATIONS:
    {med_data}

    RECENT ADHERENCE LOGS:
    {adherence_data}

    RECENT CONVERSATION HISTORY:
    {history_str}

    INSTRUCTIONS:
    1. If the user asks about their progress or specific days, refer to the 'RECENT ADHERENCE LOGS'.
    2. Use 'RECENT CONVERSATION HISTORY' to maintain continuity.
    3. Keep answers under 3 sentences. Be clinical yet kind.
    """

    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ]
    )
    return completion.choices[0].message.content   
    
    
    
    
    
    
