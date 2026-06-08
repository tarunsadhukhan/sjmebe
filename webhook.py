# webhook.py
from fastapi import FastAPI, Response, Query

app = FastAPI()
VERIFY_TOKEN = "globalerpmysecret123"

@app.get("/webhook")
def verify(
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
):
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receive():
    return Response(status_code=200)