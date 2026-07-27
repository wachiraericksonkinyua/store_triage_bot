import os
import json
import httpx
from typing import Any, Dict, List, cast
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Response
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

app = FastAPI(title="Ayutech Motors Engine & WhatsApp Webhook")

# Environment Variables
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

AYUTECH_STORE_ID = "ayutech"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class WebhookPayload(BaseModel):
    user_phone: str
    message: str

# Helper: Save lead to Supabase
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

# Helper: Save conversation turn
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

# Helper: Send reply back to user via Meta Cloud API
async def send_whatsapp_message(to_phone: str, text_message: str):
    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_TOKEN:
        print("⚠️ Meta WhatsApp credentials missing in environment variables.")
        return

    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": text_message}
    }
    
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(url, headers=headers, json=payload)
            print(f" [Meta WhatsApp API Response]: {res.status_code}")
        except Exception as e:
            print(f"❌ Failed to send WhatsApp message: {str(e)}")


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "capture_lead",
            "description": "Call this tool strictly when the customer explicitly asks to BUY, PLACE AN ORDER, DISPATCH, or requests a CALLBACK. Do NOT call this tool for general pricing or stock inquiries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "description": "e.g. Spare Part Order, Callback Request"},
                    "notes": {"type": "string", "description": "Car model and items ordered"}
                },
                "required": ["intent", "notes"]
            }
        }
    }
]

# Root endpoint check
@app.get("/")
def home():
    return {"status": "Ayutech Motors AI Engine Running"}

# 1. Verification Endpoint for Meta Dashboard setup
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
            print(" WEBHOOK_VERIFIED")
            return Response(content=challenge, status_code=200)
        else:
            raise HTTPException(status_code=403, detail="Verification token mismatch")
    raise HTTPException(status_code=400, detail="Missing verification parameters")

# 2. Webhook to process incoming WhatsApp messages from Meta
@app.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if messages:
            msg = messages[0]
            user_phone = msg.get("from")
            
            if msg.get("type") == "text":
                user_text = msg.get("text", {}).get("body", "")

                payload = WebhookPayload(user_phone=user_phone, message=user_text)
                response_data = await chat_endpoint(payload, background_tasks)
                reply_text = response_data.get("reply", "")
                
                # Send response back to user's WhatsApp
                background_tasks.add_task(send_whatsapp_message, user_phone, reply_text)

        return {"status": "success"}
    except Exception as e:
        print(f"⚠️ Webhook payload error or read event: {str(e)}")
        return {"status": "ignored"}

# 3. Direct Chat Logic Endpoint
@app.post("/chat")
async def chat_endpoint(payload: WebhookPayload, background_tasks: BackgroundTasks):
    # A. Fetch dynamic product inventory from Supabase
    try:
        products_response = supabase.table("products").select("name, category, car_model, price, stock_quantity").eq("is_available", True).execute()
        inventory_list = products_response.data or []
        
        inventory_text = ""
        for p in inventory_list:
            if isinstance(p, dict):
                p_name = p.get("name", "Item")
                p_cat = p.get("category", "General")
                p_model = p.get("car_model", "Universal")
                p_price = p.get("price", "N/A")
                p_stock = p.get("stock_quantity", 0)
                inventory_text += f"- Item: {p_name} | Category: {p_cat} | Model: {p_model} | Price: KES {p_price} | Stock: {p_stock} units\n"  
    except Exception:
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

    # C. System Prompt
    system_prompt = (
        "You are the official customer support assistant for Ayutech Motors Limited on Kirinyaga Road, Nairobi.\n"
        "Your task is to answer customer questions about car spare parts, stock availability, and pricing in a helpful, conversational tone (Sheng, Swahili, or English depending on how the customer speaks).\n\n"
        "RULES:\n"
        "1. Never say phrases like 'According to the LIVE INVENTORY' or 'In my database'. Speak naturally as an Ayutech staff member.\n"
        "2. State prices and stock clearly using the inventory list below.\n"
        "3. If a customer is ONLY asking for price or stock, answer directly. Do NOT call `capture_lead`.\n"
        "4. Call `capture_lead` ONLY when the customer explicitly says they want to BUY, ORDER, RESERVE, or ask for a CALLBACK.\n\n"
        f"INVENTORY:\n{inventory_text}"
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
                
                llm_content = message_obj.get("content")
                if llm_content:
                    bot_reply = llm_content
                else:
                    bot_reply = "Thank you! I have logged your order request for Ayutech Motors Limited. Our team will contact you shortly!"
            else:
                bot_reply = message_obj.get("content", "")

            # E. Save history asynchronously
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