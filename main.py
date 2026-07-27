import os
import json
import httpx
from typing import Any, Dict, List, cast
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

app = FastAPI(title="Ayutech Motors Inventory Engine")

GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

AYUTECH_STORE_ID = "ayutech"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class WebhookPayload(BaseModel):
    user_phone: str
    message: str

def save_lead_to_supabase(phone: str, intent: str, notes: str):
    try:
        supabase.table("leads").insert({
            "business_id": AYUTECH_STORE_ID,
            "customer_phone": phone,
            "intent": intent,
            "notes": notes
        }).execute()
        print(f" [Ayutech Lead Saved] Phone: {phone} | Intent: {intent}")
    except Exception as e:
        print(f"❌ Failed to save lead: {str(e)}")

def save_message_to_history(phone: str, role: str, content: str):
    try:
        supabase.table("conversations").insert({
            "business_id": AYUTECH_STORE_ID,
            "customer_phone": phone,
            "role": role,
            "content": content
        }).execute()
    except Exception as e:
        print(f"❌ Failed to save message history: {str(e)}")


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "capture_lead",
            "description": "Call this tool ONLY when the customer wants to buy spare parts, place an order, or requests a representative to call them back.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "description": "e.g. Spare Part Order, Quote Request"},
                    "notes": {"type": "string", "description": "Car model, year, and specific requested parts"}
                },
                "required": ["intent", "notes"]
            }
        }
    }
]


@app.post("/chat")
async def chat_endpoint(payload: WebhookPayload, background_tasks: BackgroundTasks):
    # A. Fetch dynamic product inventory from Database
    try:
        products_response = supabase.table("products").select("name, category, car_model, price, stock_quantity").eq("is_available", True).execute()
        inventory_list = products_response.data or []
        
        # Format inventory into clean readable string for LLM
        inventory_text = ""
        for p in inventory_list:
            if isinstance(p, dict):
                p_name = p.get("name", "Item")
                p_cat = p.get("category", "General")
                p_model = p.get("car_model", "Universal")
                p_price = p.get("price", "N/A")
                p_stock = p.get("stock_quantity", 0)
                inventory_text += f"- Item: {p_name} | Category: {p_cat} | Model: {p_model} | Price: KES {p_price} | Stock: {p_stock} units\n"  
    except Exception as e:
        inventory_text = "No active inventory listed."

    # B. Fetch recent chat history
    try:
        history_response = (
            supabase.table("conversations")
            .select("role, content")
            .eq("business_id", AYUTECH_STORE_ID)
            .eq("customer_phone", payload.user_phone)
            .order("created_at", desc=True)
            .limit(6)
            .execute()
        )
        raw_data = history_response.data or []
        chat_history = raw_data[::-1]
    except Exception:
        chat_history = []

    # C. System Prompt with Live Inventory Context
    system_prompt = (
        "You are the official WhatsApp AI Assistant for Ayutech Motors Limited (Located on Kirinyaga Road, Nairobi).\n"
        "Your task is to help customers check spare parts availability, pricing, and compatibility.\n\n"
        "STRICT RULES:\n"
        "1. Check the LIVE INVENTORY list below to answer pricing and availability questions accurately.\n"
        "2. If an item is out of stock or not listed in inventory, inform the customer and offer to take their details so sales reps can source it.\n"
        "3. Call `capture_lead` whenever the customer explicitly wants to order, purchase, or request a call.\n\n"
        f"LIVE INVENTORY TABLE:\n{inventory_text}"
    )

    messages_payload: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    
    for msg in chat_history:
        if isinstance(msg, dict):
            r = str(msg.get("role", "user"))
            c = str(msg.get("content", ""))
            if c:
                messages_payload.append({"role": r, "content": c})
        
    messages_payload.append({"role": "user", "content": payload.message})

    # D. Call Groq LLM
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
                            phone=payload.user_phone,
                            intent=args.get("intent", "Spare Part Order"),
                            notes=args.get("notes", payload.message)
                        )
                
                bot_reply = "Thank you! I have logged your order request for Ayutech Motors Limited. Our sales desk will verify stock and contact you shortly!"
            else:
                bot_reply = message_obj.get("content", "")

            # E. Save chat history
            background_tasks.add_task(
                save_message_to_history,
                phone=payload.user_phone,
                role="user",
                content=payload.message
            )
            background_tasks.add_task(
                save_message_to_history,
                phone=payload.user_phone,
                role="assistant",
                content=bot_reply
            )

            return {
                "store": "Ayutech Motors Limited",
                "recipient": payload.user_phone,
                "reply": bot_reply
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM request error: {str(e)}")