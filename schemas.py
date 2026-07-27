from pydantic import BaseModel

class WebhookPayload(BaseModel):
    user_phone: str
    message: str

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "calculate_delivery",
            "description": "Call this tool strictly when the customer asks for delivery fees, shipping costs, or asks how much it costs to send parts to a specific location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Location or neighborhood mentioned by the user (e.g. CBD, Westlands, Thika Road)",
                    }
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_lead",
            "description": "Call this tool strictly when the customer explicitly asks to BUY, PLACE AN ORDER, DISPATCH, or requests a CALLBACK.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "e.g. Spare Part Order, Callback Request",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Car model and items ordered",
                    },
                    "status": {
                        "type": "string",
                        "description": "AVAILABLE or NEEDS_HUMAN_ATTENTION",
                    },
                },
                "required": ["intent", "notes"],
            },
        },
    },
]