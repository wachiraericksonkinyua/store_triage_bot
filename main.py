import json
import httpx
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Response

from config import GROQ_API_KEY, WHATSAPP_VERIFY_TOKEN, AYUTECH_STORE_ID, supabase
from schemas import WebhookPayload, TOOLS_SCHEMA
from services import (
    calculate_delivery_fee,
    save_lead_to_supabase,
    save_message_to_history,
    send_whatsapp_message,
)

app = FastAPI(title="Ayutech Motors Engine & WhatsApp Webhook")


@app.get("/")
def home():
    return {"status": "Ayutech Motors AI Engine Running"}


@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
            return Response(content=challenge, status_code=200)
        else:
            raise HTTPException(status_code=403, detail="Verification token mismatch")
    raise HTTPException(status_code=400, detail="Missing verification parameters")


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

                background_tasks.add_task(send_whatsapp_message, user_phone, reply_text)

        return {"status": "success"}
    except Exception as e:
        print(f"⚠️ Webhook error: {str(e)}")
        return {"status": "ignored"}


@app.post("/chat")
async def chat_endpoint(payload: WebhookPayload, background_tasks: BackgroundTasks):
    # 1. Fetch live stock inventory from Supabase
    try:
        products_response = (
            supabase.table("products")
            .select("name, category, car_model, price, stock_quantity")
            .execute()
        )
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

    # 2. Fetch recent conversation history
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

    # 3. System Prompt
    system_prompt = (
        "You are the official customer support assistant for Ayutech Motors Limited on Kirinyaga Road, Nairobi.\n"
        "Your job is to answer customer questions naturally in Sheng, Swahili, or English.\n\n"
        "STRICT BEHAVIOR RULES:\n"
        "1. GENERAL INQUIRIES & PRICING: If the user asks for prices, stock, or greetings (e.g. 'hi', 'how much is a hub', 'do you have shock absorbers'), ANSWER DIRECTLY with the price and stock quantity. DO NOT call `capture_lead`.\n"
        "2. DELIVERY COSTS: When a customer asks about delivery fees, shipping rates, or delivery to a specific location, call `calculate_delivery`.\n"
        "3. EXPLICIT ORDERS: Call `capture_lead` ONLY when the customer explicitly states they want to BUY, ORDER, RESERVE, or request DELIVERY.\n"
        "4. OUT OF STOCK / UNLISTED PARTS: If the part is NOT in stock or not listed, state: 'Nime-check stock, hiyo part haipatikani kwa sasa lakini nimemjulisha owner wetu wa Kirinyaga Road akutafute!' and call `capture_lead` with status 'NEEDS_HUMAN_ATTENTION'.\n"
        "5. NATURAL CONVERSATION: Never mention 'database' or 'live inventory'. Speak like a friendly human shop attendant.\n\n"
        f"LIVE INVENTORY:\n{inventory_text}"
    )

    messages_payload: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    for msg in chat_history:
        if isinstance(msg, dict):
            r = str(msg.get("role", "user"))
            c = str(msg.get("content", ""))
            if c:
                messages_payload.append({"role": r, "content": c})

    messages_payload.append({"role": "user", "content": payload.message})

    # 4. Call Groq LLM
    async with httpx.AsyncClient() as client:
        try:
            llm_response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": messages_payload,
                    "tools": TOOLS_SCHEMA,
                    "tool_choice": "auto",
                    "temperature": 0,
                },
                timeout=10.0,
            )

            if llm_response.status_code != 200:
                raise HTTPException(
                    status_code=500, detail=f"Groq API Error: {llm_response.text}"
                )

            result = llm_response.json()
            message_obj = result["choices"][0]["message"]

            # Initialize default variable to avoid unbound variable warnings
            bot_reply = ""

            tool_calls = message_obj.get("tool_calls")
            if tool_calls:
                for tool_call in tool_calls:
                    func_name = tool_call["function"]["name"]
                    args = json.loads(tool_call["function"]["arguments"])

                    if func_name == "calculate_delivery":
                        location = args.get("location", "")
                        delivery_quote = calculate_delivery_fee(location)
                        bot_reply = f"{delivery_quote} Tunatuma na rider ama courier mara moja!"

                    elif func_name == "capture_lead":
                        background_tasks.add_task(
                            save_lead_to_supabase,
                            phone=payload.user_phone,
                            intent=args.get("intent", "Spare Part Order"),
                            notes=args.get("notes", payload.message),
                            status=args.get("status", "Pending")
                        )

                        llm_content = message_obj.get("content")
                        if llm_content:
                            bot_reply = llm_content
                        else:
                            bot_reply = f"Asante! Nime-log order yako ya '{args.get('intent', 'Spare Part')}'. Owner wetu wa Kirinyaga Road ata-contact wewe sasa hivi!"
            else:
                bot_reply = message_obj.get("content", "")

            # Log conversations asynchronously
            background_tasks.add_task(
                save_message_to_history,
                phone=payload.user_phone,
                role="user",
                content=payload.message,
            )
            background_tasks.add_task(
                save_message_to_history,
                phone=payload.user_phone,
                role="assistant",
                content=bot_reply,
            )

            return {
                "store": "Ayutech Motors Limited",
                "recipient": payload.user_phone,
                "reply": bot_reply,
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM request error: {str(e)}")