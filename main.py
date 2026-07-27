import os
import json
import httpx
from typing import Any, Dict, List, cast
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

app = FastAPI(title="Track W: Memory-Aware Triage Engine")

GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class WebhookPayload(BaseModel):
    business_id: str
    user_phone: str
    message: str

def save_lead_to_supabase(business_id: str, phone: str, intent: str, notes: str):
    try:
        supabase.table("leads").insert({
            "business_id": business_id,
            "customer_phone": phone,
            "intent": intent,
            "notes": notes
        }).execute()
        print(f" [Lead Saved via Tool] Business: {business_id} | Phone: {phone}")
    except Exception as e:
        print(f"❌ Failed to save lead: {str(e)}")

def save_message_to_history(business_id: str, phone: str, role: str, content: str):
    try:
        supabase.table("conversations").insert({
            "business_id": business_id,
            "customer_phone": phone,
            "role": role,
            "content": content
        }).execute()
        print(f" [History Saved] Role: {role}")
    except Exception as e:
        print(f"❌ Failed to save message history: {str(e)}")


# Simplified tool schema
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "capture_lead",
            "description": "Call this tool ONLY when the customer explicitly asks to BUY, ORDER, RESERVE an item, or requests a HUMAN callback.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "notes": {"type": "string"}
                },
                "required": ["intent", "notes"]
            }
        }
    }
]


@app.post("/chat")
async def chat_endpoint(payload: WebhookPayload, background_tasks: BackgroundTasks):
    # A. Fetch store context
    try:
        response = supabase.table("stores").select("*").eq("id", payload.business_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail=f"Business '{payload.business_id}' not found.")
        
        store = cast(Dict[str, Any], response.data[0])
        store_name = str(store.get("name", "Store"))
        store_context = str(store.get("context_data", ""))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")

    # B. Fetch recent chat history
    try:
        history_response = (
            supabase.table("conversations")
            .select("role, content")
            .eq("business_id", payload.business_id)
            .eq("customer_phone", payload.user_phone)
            .order("created_at", desc=True)
            .limit(6)
            .execute()
        )
        raw_data = history_response.data or []
        chat_history = raw_data[::-1]
    except Exception:
        chat_history = []

    # C. System Prompt
    system_prompt = (
        f"You are a store assistant for {store_name}.\n"
        f"Answer customer questions accurately using ONLY the context provided below.\n"
        f"Do NOT invent or use functions outside of `capture_lead`.\n\n"
        f"CONTEXT:\n{store_context}"
    )

    messages_payload: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    
    for msg in chat_history:
        if isinstance(msg, dict):
            r = str(msg.get("role", "user"))
            c = str(msg.get("content", ""))
            if c:
                messages_payload.append({"role": r, "content": c})
        
    messages_payload.append({"role": "user", "content": payload.message})

    # D. Call Groq API with llama-3.3-70b-versatile
    async with httpx.AsyncClient() as client:
        try:
            llm_response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": messages_payload,
                    "tools": TOOLS_SCHEMA,
                    "tool_choice": "auto",
                    "temperature": 0
                },
                timeout=10.0
            )
            
            if llm_response.status_code != 200:
                print(f"❌ Groq Error: {llm_response.text}")
                raise HTTPException(status_code=500, detail=f"Groq API Error: {llm_response.text}")

            result = llm_response.json()
            message_obj = result["choices"][0]["message"]
            
            tool_calls = message_obj.get("tool_calls")
            if tool_calls:
                for tool_call in tool_calls:
                    if tool_call["function"]["name"] == "capture_lead":
                        args = json.loads(tool_call["function"]["arguments"])
                        background_tasks.add_task(
                            save_lead_to_supabase,
                            business_id=payload.business_id,
                            phone=payload.user_phone,
                            intent=args.get("intent", "General Lead"),
                            notes=args.get("notes", payload.message)
                        )
                
                bot_reply = f"I've logged your request for our team at {store_name}. Someone will reach out to you shortly!"
            else:
                bot_reply = message_obj.get("content", "")

            # E. Save history asynchronously
            background_tasks.add_task(
                save_message_to_history,
                business_id=payload.business_id,
                phone=payload.user_phone,
                role="user",
                content=payload.message
            )
            background_tasks.add_task(
                save_message_to_history,
                business_id=payload.business_id,
                phone=payload.user_phone,
                role="assistant",
                content=bot_reply
            )

            return {
                "business_id": payload.business_id,
                "recipient": payload.user_phone,
                "reply": bot_reply
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM request error: {str(e)}")