# main.py - BookieVerse P2P Sportsbook
# Deploy this to Render.com for free hosting

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import hashlib
import jwt
from datetime import datetime, timedelta
import uvicorn
import os

app = FastAPI(title="BookieVerse - P2P Sportsbook")

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.getenv("SECRET_KEY", "bookieverse-secret-change-in-production")

# In-memory storage (resets on restart - perfect for beta testing)
users_db = {}
lines_db = {}
bets_db = {}
games_db = {
    1: {"id": 1, "home": "Lakers", "away": "Warriors", "date": "2026-02-12", "time": "7:30 PM"},
    2: {"id": 2, "home": "Celtics", "away": "Heat", "date": "2026-02-12", "time": "8:00 PM"},
    3: {"id": 3, "home": "Bucks", "away": "Nets", "date": "2026-02-13", "time": "7:00 PM"},
    4: {"id": 4, "home": "Chiefs", "away": "Bills", "date": "2026-02-15", "time": "4:00 PM"},
    5: {"id": 5, "home": "Eagles", "away": "Cowboys", "date": "2026-02-15", "time": "8:00 PM"},
}

# Pydantic models
class UserCreate(BaseModel):
    username: str
    password: str = "demo123"

class LineCreate(BaseModel):
    game_id: int
    type: str
    side: str
    value: float
    amount: float

class TakeLine(BaseModel):
    line_id: str

# Helper functions
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_token(user_id: str) -> str:
    payload = {"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=7)}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("user_id")
    except:
        return None

# API Routes
@app.get("/")
def home():
    return {
        "message": "🎯 BookieVerse API is running!",
        "app": "/app",
        "docs": "/docs",
        "status": "online"
    }

@app.get("/health")
def health():
    return {"status": "healthy", "users": len(users_db), "lines": len(lines_db), "bets": len(bets_db)}

@app.post("/api/auth/register")
def register(user: UserCreate):
    if user.username in [u["username"] for u in users_db.values()]:
        raise HTTPException(400, "Username already exists")
    
    user_id = f"user_{len(users_db) + 1}"
    users_db[user_id] = {
        "id": user_id,
        "username": user.username,
        "password": hash_password(user.password),
        "balance": 10000,
        "profit": 0,
        "wins": 0,
        "losses": 0,
        "lines_created": 0
    }
    
    token = create_token(user_id)
    return {
        "token": token,
        "user": {
            "id": user_id,
            "username": user.username,
            "balance": 10000,
            "profit": 0
        }
    }

@app.post("/api/auth/login")
def login(user: UserCreate):
    for uid, u in users_db.items():
        if u["username"] == user.username and u["password"] == hash_password(user.password):
            token = create_token(uid)
            return {
                "token": token,
                "user": {
                    "id": uid,
                    "username": u["username"],
                    "balance": u["balance"],
                    "profit": u["profit"],
                    "wins": u["wins"],
                    "losses": u["losses"]
                }
            }
    raise HTTPException(401, "Invalid credentials")

@app.get("/api/games")
def get_games():
    return list(games_db.values())

@app.get("/api/lines")
def get_lines():
    return [l for l in lines_db.values() if l["status"] == "open"]

@app.post("/api/lines")
def create_line(line: LineCreate, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    user = users_db[user_id]
    if user["balance"] < line.amount:
        raise HTTPException(400, "Insufficient balance")
    
    line_id = f"line_{len(lines_db) + 1}"
    game = games_db.get(line.game_id)
    
    lines_db[line_id] = {
        "id": line_id,
        "bookie_id": user_id,
        "bookie_name": user["username"],
        "game_id": line.game_id,
        "game": f"{game['away']} @ {game['home']}",
        "date": game["date"],
        "type": line.type,
        "side": line.side,
        "value": line.value,
        "amount": line.amount,
        "odds": -110,
        "status": "open"
    }
    
    user["balance"] -= line.amount
    user["lines_created"] += 1
    
    return {"message": "Line created", "line_id": line_id}

@app.post("/api/lines/take")
def take_line(take: TakeLine, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    line = lines_db.get(take.line_id)
    if not line or line["status"] != "open":
        raise HTTPException(404, "Line not available")
    
    if line["bookie_id"] == user_id:
        raise HTTPException(400, "Can't bet against your own line")
    
    user = users_db[user_id]
    if user["balance"] < line["amount"]:
        raise HTTPException(400, "Insufficient balance")
    
    bet_id = f"bet_{len(bets_db) + 1}"
    bets_db[bet_id] = {
        "id": bet_id,
        "line_id": take.line_id,
        "bookie_id": line["bookie_id"],
        "bookie_name": line["bookie_name"],
        "bettor_id": user_id,
        "bettor_name": user["username"],
        "game": line["game"],
        "type": line["type"],
        "bookie_side": line["side"],
        "bettor_side": "away" if line["side"] == "home" else "home",
        "value": line["value"],
        "amount": line["amount"],
        "status": "pending"
    }
    
    user["balance"] -= line["amount"]
    line["status"] = "matched"
    
    return {"message": "Bet placed", "bet_id": bet_id}

@app.get("/api/bets")
def get_bets(token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    user_bets = [b for b in bets_db.values() 
                 if b["bookie_id"] == user_id or b["bettor_id"] == user_id]
    return user_bets

@app.post("/api/bets/{bet_id}/settle")
def settle_bet(bet_id: str, winner: str, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    bet = bets_db.get(bet_id)
    if not bet:
        raise HTTPException(404, "Bet not found")
    
    if user_id not in [bet["bookie_id"], bet["bettor_id"]]:
        raise HTTPException(403, "Not authorized")
    
    rake = 0.05
    payout = bet["amount"] * 2 * (1 - rake)
    
    bookie = users_db[bet["bookie_id"]]
    bettor = users_db[bet["bettor_id"]]
    
    if winner == "bookie":
        bookie["balance"] += payout
        bookie["profit"] += (payout - bet["amount"])
        bookie["wins"] += 1
        bettor["profit"] -= bet["amount"]
        bettor["losses"] += 1
    else:
        bettor["balance"] += payout
        bettor["profit"] += (payout - bet["amount"])
        bettor["wins"] += 1
        bookie["profit"] -= bet["amount"]
        bookie["losses"] += 1
    
    bet["status"] = "settled"
    bet["winner"] = winner
    
    return {"message": "Bet settled", "winner": winner}

@app.get("/api/leaderboard")
def leaderboard():
    sorted_users = sorted(users_db.values(), key=lambda x: x["profit"], reverse=True)
    return sorted_users[:10]

@app.get("/api/user")
def get_user(token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    user = users_db[user_id]
    return {
        "id": user["id"],
        "username": user["username"],
        "balance": user["balance"],
        "profit": user["profit"],
        "wins": user["wins"],
        "losses": user["losses"],
        "lines_created": user["lines_created"]
    }

@app.get("/api/stats")
def get_stats():
    return {
        "total_users": len(users_db),
        "active_lines": len([l for l in lines_db.values() if l["status"] == "open"]),
        "total_bets": len(bets_db),
        "total_volume": sum(b["amount"] for b in bets_db.values())
    }

# Frontend HTML (embedded)
@app.get("/app", response_class=HTMLResponse)
def serve_app():
    with open("index.html", "r") as f:
        return f.read()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
