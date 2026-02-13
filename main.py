# main.py - BookieVerse COMPLETE - All Features + New Features

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
import hashlib
import jwt
from datetime import datetime, timedelta
import uvicorn
import os
import requests
from apscheduler.schedulers.background import BackgroundScheduler
import stripe

app = FastAPI(title="BookieVerse - Complete Edition")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.getenv("SECRET_KEY", "bookieverse-secret-change-in-production")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

HOURLY_CURRENCY = 5
STARTING_BALANCE = 1000
MAX_OFFLINE_HOURS = 72

CREDIT_PACKAGES = {
    "small": {"amount": 299, "credits": 300, "name": "$2.99 - 300 Credits"},
    "medium": {"amount": 499, "credits": 500, "name": "$4.99 - 500 Credits"},
    "large": {"amount": 999, "credits": 1100, "name": "$9.99 - 1,100 Credits (+10%)"},
    "xl": {"amount": 1999, "credits": 2400, "name": "$19.99 - 2,400 Credits (+20%)"},
    "mega": {"amount": 4999, "credits": 6500, "name": "$49.99 - 6,500 Credits (+30%)"}
}

# Storage
users_db = {}
lines_db = {}
bets_db = {}
games_db = {}
futures_db = {}
parlays_db = {}
groups_db = {}
ratings_db = {}
follows_db = {}
purchases_db = {}

SPORTS = ['basketball_nba', 'americanfootball_nfl']

# Pydantic Models
class UserCreate(BaseModel):
    username: str
    password: str

class LineCreate(BaseModel):
    game_id: str
    type: str
    side: str
    value: float
    amount: float
    max_bettors: Optional[int] = None
    max_bet_per_user: Optional[float] = None
    max_total_action: Optional[float] = None
    is_private: Optional[bool] = False
    group_id: Optional[str] = None

class LineUpdate(BaseModel):
    value: Optional[float] = None
    amount: Optional[float] = None
    max_bettors: Optional[int] = None

class TakeLine(BaseModel):
    line_id: str

class ParlayCreate(BaseModel):
    line_ids: List[str]
    amount: float

class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None

class GroupInvite(BaseModel):
    group_id: str
    username: str

class RateBookie(BaseModel):
    bookie_id: str
    rating: int
    comment: Optional[str] = None

class CreditPurchase(BaseModel):
    package: str

# Helper Functions
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

def apply_hourly_currency(user_id: str):
    user = users_db.get(user_id)
    if not user:
        return
    
    now = datetime.utcnow()
    last_accrual = user.get("last_accrual")
    
    if not last_accrual:
        user["last_accrual"] = now
        return
    
    hours_passed = (now - last_accrual).total_seconds() / 3600
    hours_passed = min(hours_passed, MAX_OFFLINE_HOURS)
    currency_to_add = int(hours_passed) * HOURLY_CURRENCY
    
    if currency_to_add > 0:
        user["balance"] += currency_to_add
        user["last_accrual"] = now
        user["total_earned"] = user.get("total_earned", 0) + currency_to_add

def get_bookie_rating(bookie_id: str) -> dict:
    bookie_ratings = [r for r in ratings_db.values() if r["bookie_id"] == bookie_id]
    if not bookie_ratings:
        return {"average": 0, "count": 0}
    total = sum(r["rating"] for r in bookie_ratings)
    avg = total / len(bookie_ratings)
    return {"average": round(avg, 2), "count": len(bookie_ratings)}

def get_bookie_stats(bookie_id: str) -> dict:
    user = users_db.get(bookie_id)
    if not user:
        return {}
    
    bookie_lines = [l for l in lines_db.values() if l["bookie_id"] == bookie_id]
    bookie_bets = [b for b in bets_db.values() if b["bookie_id"] == bookie_id and b["status"] == "settled"]
    
    total_lines = len(bookie_lines)
    active_lines = len([l for l in bookie_lines if l["status"] == "open"])
    
    wins = len([b for b in bookie_bets if b.get("winner") == "bookie"])
    losses = len([b for b in bookie_bets if b.get("winner") == "bettor"])
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    
    rating_data = get_bookie_rating(bookie_id)
    followers = len([f for f in follows_db.values() if f["bookie_id"] == bookie_id])
    
    return {
        "id": bookie_id,
        "username": user["username"],
        "total_lines_created": total_lines,
        "active_lines": active_lines,
        "settled_bets": len(bookie_bets),
        "win_rate": round(win_rate, 1),
        "wins": wins,
        "losses": losses,
        "rating": rating_data["average"],
        "rating_count": rating_data["count"],
        "followers": followers,
        "profit": user["profit"]
    }

def is_game_started(game_id: str) -> bool:
    game = games_db.get(game_id)
    if not game:
        return False
    if game.get('status') in ['live', 'final']:
        return True
    if game.get('commence_time'):
        try:
            commence_time = datetime.fromisoformat(game['commence_time'].replace('Z', '+00:00'))
            return datetime.now(commence_time.tzinfo) >= commence_time
        except:
            pass
    return False

def migrate_old_users():
    for user_id, user in users_db.items():
        if "last_accrual" not in user:
            user["last_accrual"] = datetime.utcnow()
        if "total_earned" not in user:
            user["total_earned"] = 0
        if "total_purchased" not in user:
            user["total_purchased"] = 0
        if "groups" not in user:
            user["groups"] = []
        if "lines_created" not in user:
            user["lines_created"] = 0
    print(f"✅ Migrated {len(users_db)} users")

def determine_bet_winner(bet: dict, line: dict, home_score: int, away_score: int) -> Optional[str]:
    bet_type = line.get("type")
    value = line.get("value", 0)
    bookie_side = bet.get("bookie_side")
    score_diff = home_score - away_score
    
    if bet_type == "spread":
        if bookie_side == "home":
            adjusted_diff = score_diff + value
            return "bookie" if adjusted_diff > 0 else "bettor"
        else:
            adjusted_diff = score_diff - value
            return "bookie" if adjusted_diff < 0 else "bettor"
    elif bet_type == "moneyline":
        if bookie_side == "home":
            return "bookie" if home_score > away_score else "bettor"
        else:
            return "bookie" if away_score > home_score else "bettor"
    elif bet_type == "total":
        total_points = home_score + away_score
        if bookie_side == "over":
            return "bookie" if total_points > value else "bettor"
        else:
            return "bookie" if total_points < value else "bettor"
    return None

def settle_bet_automatically(bet_id: str, winner: str):
    bet = bets_db.get(bet_id)
    if not bet or bet["status"] != "pending":
        return
    
    rake = 0.05
    payout = bet["amount"] * 2 * (1 - rake)
    
    bookie = users_db.get(bet["bookie_id"])
    bettor = users_db.get(bet["bettor_id"])
    
    if not bookie or not bettor:
        return
    
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
    bet["settled_at"] = datetime.utcnow().isoformat()
    bet["auto_settled"] = True

def load_demo_games():
    global games_db
    now = datetime.utcnow()
    games_db = {
        'demo_1': {"id": 'demo_1', "home": "Lakers", "away": "Warriors", "sport": "NBA", "date": "2026-02-14", "time": "7:30 PM", "status": "upcoming", "commence_time": (now + timedelta(hours=2)).isoformat(), "home_score": None, "away_score": None},
        'demo_2': {"id": 'demo_2', "home": "Celtics", "away": "Heat", "sport": "NBA", "date": "2026-02-14", "time": "8:00 PM", "status": "upcoming", "commence_time": (now + timedelta(hours=3)).isoformat(), "home_score": None, "away_score": None},
    }

def load_default_futures():
    global futures_db
    futures_db = {
        'future_1': {'id': 'future_1', 'market_name': 'NBA Championship Winner', 'sport': 'NBA', 'close_date': '2026-06-01', 'settle_date': '2026-06-30', 'status': 'open', 'options': ['Lakers', 'Celtics', 'Warriors', 'Bucks', 'Nuggets']},
        'future_2': {'id': 'future_2', 'market_name': 'Super Bowl Winner', 'sport': 'NFL', 'close_date': '2026-02-05', 'settle_date': '2026-02-09', 'status': 'open', 'options': ['Chiefs', 'Bills', 'Eagles', 'Cowboys', '49ers']}
    }

@app.on_event("startup")
async def startup_event():
    migrate_old_users()
    load_demo_games()
    load_default_futures()
    scheduler = BackgroundScheduler()
    scheduler.add_job(load_demo_games, 'interval', hours=1)
    scheduler.start()

# API Routes
@app.get("/")
def home():
    return {"message": "🎯 BookieVerse", "app": "/app", "features": ["all_features"]}

@app.post("/api/auth/register")
def register(user: UserCreate):
    if len(user.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if user.username in [u["username"] for u in users_db.values()]:
        raise HTTPException(400, "Username already taken")
    
    user_id = f"user_{len(users_db) + 1}"
    users_db[user_id] = {
        "id": user_id, "username": user.username, "password": hash_password(user.password),
        "balance": STARTING_BALANCE, "profit": 0, "wins": 0, "losses": 0, "lines_created": 0,
        "last_accrual": datetime.utcnow(), "total_earned": 0, "total_purchased": 0, "groups": []
    }
    token = create_token(user_id)
    return {"token": token, "user": {"id": user_id, "username": user.username, "balance": STARTING_BALANCE}}

@app.post("/api/auth/login")
def login(user: UserCreate):
    for uid, u in users_db.items():
        if u["username"] == user.username and u["password"] == hash_password(user.password):
            apply_hourly_currency(uid)
            token = create_token(uid)
            return {"token": token, "user": {"id": uid, "username": u["username"], "balance": u["balance"], "profit": u["profit"]}}
    raise HTTPException(401, "Invalid username or password")

@app.get("/api/games")
def get_games():
    return list(games_db.values())

@app.get("/api/futures")
def get_futures():
    return list(futures_db.values())

@app.get("/api/lines")
def get_lines(token: Optional[str] = None):
    user_id = verify_token(token) if token else None
    user = users_db.get(user_id) if user_id else None
    all_lines = [l for l in lines_db.values() if l["status"] == "open"]
    if user:
        user_groups = user.get("groups", [])
        return [l for l in all_lines if not l.get("is_private") or l.get("group_id") in user_groups]
    return [l for l in all_lines if not l.get("is_private")]

@app.post("/api/lines")
def create_line(line: LineCreate, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    apply_hourly_currency(user_id)
    user = users_db[user_id]
    if user["balance"] < line.amount:
        raise HTTPException(400, "Insufficient balance")
    if line.is_private:
        if not line.group_id:
            raise HTTPException(400, "Private lines require a group_id")
        if line.group_id not in user.get("groups", []):
            raise HTTPException(403, "You're not in this group")
    
    if line.type == "future":
        market = futures_db.get(line.game_id)
        if not market:
            raise HTTPException(404, "Future market not found")
        game_display = market['market_name']
        sport = market.get('sport', 'FUTURE')
    else:
        game = games_db.get(line.game_id)
        if not game:
            raise HTTPException(404, "Game not found")
        if is_game_started(line.game_id):
            raise HTTPException(400, "Cannot create line - game has already started")
        game_display = f"{game['away']} @ {game['home']}"
        sport = game.get('sport', 'NBA')
    
    line_id = f"line_{len(lines_db) + 1}"
    lines_db[line_id] = {
        "id": line_id, "bookie_id": user_id, "bookie_name": user["username"],
        "game_id": line.game_id, "game": game_display, "sport": sport, "type": line.type,
        "side": line.side, "value": line.value, "amount": line.amount, "odds": -110,
        "status": "open", "max_bettors": line.max_bettors, "max_bet_per_user": line.max_bet_per_user,
        "max_total_action": line.max_total_action, "current_bettors": 0, "total_action": 0,
        "is_private": line.is_private or False, "group_id": line.group_id, "created_at": datetime.utcnow().isoformat()
    }
    user["balance"] -= line.amount
    user["lines_created"] += 1
    return {"message": "Line created", "line_id": line_id}

@app.delete("/api/lines/{line_id}")
def cancel_line(line_id: str, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    line = lines_db.get(line_id)
    if not line:
        raise HTTPException(404, "Line not found")
    if line["bookie_id"] != user_id:
        raise HTTPException(403, "Not your line")
    if line["status"] != "open":
        raise HTTPException(400, "Can't cancel matched line")
    if line["current_bettors"] > 0:
        raise HTTPException(400, "Line has bets on it")
    if is_game_started(line.get("game_id")):
        raise HTTPException(400, "Cannot cancel - game has started")
    user = users_db[user_id]
    user["balance"] += line["amount"]
    line["status"] = "cancelled"
    return {"message": "Line cancelled", "refunded": line["amount"]}

@app.put("/api/lines/{line_id}")
def edit_line(line_id: str, updates: LineUpdate, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    line = lines_db.get(line_id)
    if not line:
        raise HTTPException(404, "Line not found")
    if line["bookie_id"] != user_id:
        raise HTTPException(403, "Not your line")
    if line["status"] != "open":
        raise HTTPException(400, "Can't edit matched line")
    if line["current_bettors"] > 0:
        raise HTTPException(400, "Line has bets on it")
    if is_game_started(line.get("game_id")):
        raise HTTPException(400, "Cannot edit - game has started")
    if updates.value is not None:
        line["value"] = updates.value
    if updates.amount is not None:
        user = users_db[user_id]
        balance_diff = updates.amount - line["amount"]
        if balance_diff > 0 and user["balance"] < balance_diff:
            raise HTTPException(400, "Insufficient balance for increase")
        user["balance"] -= balance_diff
        line["amount"] = updates.amount
    if updates.max_bettors is not None:
        line["max_bettors"] = updates.max_bettors
    return {"message": "Line updated", "line": line}

@app.post("/api/lines/take")
def take_line(take: TakeLine, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    apply_hourly_currency(user_id)
    line = lines_db.get(take.line_id)
    if not line or line["status"] != "open":
        raise HTTPException(404, "Line not available")
    if is_game_started(line.get("game_id")):
        raise HTTPException(400, "Cannot bet - game has started")
    if line["bookie_id"] == user_id:
        raise HTTPException(400, "Can't bet against your own line")
    user = users_db[user_id]
    if line.get("max_bettors") and line["current_bettors"] >= line["max_bettors"]:
        raise HTTPException(400, f"Line full")
    if line.get("max_bet_per_user") and line["amount"] > line["max_bet_per_user"]:
        raise HTTPException(400, f"Exceeds max bet")
    if line.get("max_total_action") and line["total_action"] + line["amount"] > line["max_total_action"]:
        raise HTTPException(400, f"Exceeds total action limit")
    if user["balance"] < line["amount"]:
        raise HTTPException(400, "Insufficient balance")
    
    bet_id = f"bet_{len(bets_db) + 1}"
    bets_db[bet_id] = {
        "id": bet_id, "line_id": take.line_id, "bookie_id": line["bookie_id"],
        "bookie_name": line["bookie_name"], "bettor_id": user_id, "bettor_name": user["username"],
        "game": line["game"], "game_id": line["game_id"], "sport": line.get("sport", "NBA"),
        "type": line["type"], "bookie_side": line["side"],
        "bettor_side": "away" if line["side"] == "home" else "home",
        "value": line["value"], "amount": line["amount"], "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }
    user["balance"] -= line["amount"]
    line["status"] = "matched"
    line["current_bettors"] += 1
    line["total_action"] += line["amount"]
    return {"message": "Bet placed", "bet_id": bet_id}

@app.post("/api/parlays")
def create_parlay(parlay: ParlayCreate, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    apply_hourly_currency(user_id)
    if len(parlay.line_ids) < 2 or len(parlay.line_ids) > 10:
        raise HTTPException(400, "Parlay needs 2-10 legs")
    user = users_db[user_id]
    if user["balance"] < parlay.amount:
        raise HTTPException(400, "Insufficient balance")
    
    legs = []
    for line_id in parlay.line_ids:
        line = lines_db.get(line_id)
        if not line or line["status"] != "open":
            raise HTTPException(400, f"Line {line_id} not available")
        if is_game_started(line.get("game_id")):
            raise HTTPException(400, f"Cannot bet on {line['game']} - game has started")
        if line["bookie_id"] == user_id:
            raise HTTPException(400, "Can't bet against your own line in parlay")
        legs.append({
            "line_id": line_id, "game": line["game"], "game_id": line.get("game_id"),
            "type": line["type"], "side": line["side"], "value": line["value"], "status": "pending"
        })
        line["current_bettors"] += 1
        line["total_action"] += parlay.amount / len(parlay.line_ids)
    
    multiplier = 2.5 ** len(parlay.line_ids)
    potential_payout = parlay.amount * multiplier * 0.95
    parlay_id = f"parlay_{len(parlays_db) + 1}"
    parlays_db[parlay_id] = {
        "id": parlay_id, "bettor_id": user_id, "bettor_name": user["username"],
        "legs": legs, "amount": parlay.amount, "potential_payout": potential_payout,
        "status": "pending", "created_at": datetime.utcnow().isoformat()
    }
    user["balance"] -= parlay.amount
    return {"message": "Parlay created", "parlay_id": parlay_id, "potential_payout": potential_payout}

@app.get("/api/bets")
def get_bets(token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    apply_hourly_currency(user_id)
    user_bets = [b for b in bets_db.values() if b["bookie_id"] == user_id or b["bettor_id"] == user_id]
    user_parlays = [p for p in parlays_db.values() if p["bettor_id"] == user_id]
    return {"single_bets": user_bets, "parlays": user_parlays}

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
    if bet["status"] != "pending":
        raise HTTPException(400, "Bet already settled")
    settle_bet_automatically(bet_id, winner)
    return {"message": "Bet settled", "winner": winner}

@app.get("/api/bookie/{bookie_id}/profile")
def get_bookie_profile(bookie_id: str):
    stats = get_bookie_stats(bookie_id)
    if not stats:
        raise HTTPException(404, "Bookie not found")
    return stats

@app.post("/api/bookie/rate")
def rate_bookie(rating_data: RateBookie, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    if rating_data.rating < 1 or rating_data.rating > 5:
        raise HTTPException(400, "Rating must be 1-5")
    user_bets = [b for b in bets_db.values() if b["bettor_id"] == user_id and b["bookie_id"] == rating_data.bookie_id and b["status"] == "settled"]
    if not user_bets:
        raise HTTPException(400, "You haven't bet with this bookie")
    rating_id = f"rating_{len(ratings_db) + 1}"
    ratings_db[rating_id] = {
        "id": rating_id, "bookie_id": rating_data.bookie_id, "user_id": user_id,
        "rating": rating_data.rating, "comment": rating_data.comment,
        "created_at": datetime.utcnow().isoformat()
    }
    return {"message": "Rating submitted"}

@app.post("/api/bookie/{bookie_id}/follow")
def follow_bookie(bookie_id: str, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    if bookie_id not in users_db:
        raise HTTPException(404, "Bookie not found")
    if bookie_id == user_id:
        raise HTTPException(400, "Can't follow yourself")
    existing = [f for f in follows_db.values() if f["user_id"] == user_id and f["bookie_id"] == bookie_id]
    if existing:
        raise HTTPException(400, "Already following")
    follow_id = f"follow_{len(follows_db) + 1}"
    follows_db[follow_id] = {
        "id": follow_id, "user_id": user_id, "bookie_id": bookie_id,
        "created_at": datetime.utcnow().isoformat()
    }
    return {"message": "Now following"}

@app.delete("/api/bookie/{bookie_id}/follow")
def unfollow_bookie(bookie_id: str, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    follow = None
    for f in follows_db.values():
        if f["user_id"] == user_id and f["bookie_id"] == bookie_id:
            follow = f
            break
    if not follow:
        raise HTTPException(404, "Not following this bookie")
    del follows_db[follow["id"]]
    return {"message": "Unfollowed"}

@app.get("/api/bookie/following")
def get_following(token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user_follows = [f for f in follows_db.values() if f["user_id"] == user_id]
    following = []
    for follow in user_follows:
        stats = get_bookie_stats(follow["bookie_id"])
        if stats:
            following.append(stats)
    return following

@app.get("/api/users/search")
def search_users(q: Optional[str] = None, sort: Optional[str] = "rating"):
    all_users = list(users_db.values())
    if q:
        q_lower = q.lower()
        all_users = [u for u in all_users if q_lower in u["username"].lower()]
    users_with_stats = []
    for user in all_users:
        stats = get_bookie_stats(user["id"])
        if stats:
            users_with_stats.append(stats)
    if sort == "rating":
        users_with_stats.sort(key=lambda x: x.get("rating", 0), reverse=True)
    elif sort == "profit":
        users_with_stats.sort(key=lambda x: x.get("profit", 0), reverse=True)
    elif sort == "win_rate":
        users_with_stats.sort(key=lambda x: x.get("win_rate", 0), reverse=True)
    elif sort == "followers":
        users_with_stats.sort(key=lambda x: x.get("followers", 0), reverse=True)
    return users_with_stats[:50]

@app.post("/api/groups")
def create_group(group_data: GroupCreate, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = users_db[user_id]
    group_id = f"group_{len(groups_db) + 1}"
    groups_db[group_id] = {
        "id": group_id, "name": group_data.name, "description": group_data.description,
        "creator_id": user_id, "creator_name": user["username"], "members": [user_id],
        "created_at": datetime.utcnow().isoformat()
    }
    if "groups" not in user:
        user["groups"] = []
    user["groups"].append(group_id)
    return {"message": "Group created", "group_id": group_id}

@app.post("/api/groups/invite")
def invite_to_group(invite: GroupInvite, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    group = groups_db.get(invite.group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if user_id not in group["members"]:
        raise HTTPException(403, "You're not in this group")
    invitee = None
    for u in users_db.values():
        if u["username"] == invite.username:
            invitee = u
            break
    if not invitee:
        raise HTTPException(404, "User not found")
    if invitee["id"] in group["members"]:
        raise HTTPException(400, "User already in group")
    group["members"].append(invitee["id"])
    if "groups" not in invitee:
        invitee["groups"] = []
    invitee["groups"].append(invite.group_id)
    return {"message": f"{invite.username} added to group"}

@app.get("/api/groups")
def get_user_groups(token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = users_db[user_id]
    user_group_ids = user.get("groups", [])
    user_groups = []
    for group_id in user_group_ids:
        group = groups_db.get(group_id)
        if group:
            user_groups.append({
                **group, "member_count": len(group["members"]),
                "is_creator": group["creator_id"] == user_id
            })
    return user_groups

@app.get("/api/shop/packages")
def get_packages():
    return CREDIT_PACKAGES

@app.post("/api/shop/create-checkout")
async def create_checkout(purchase: CreditPurchase, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    if not STRIPE_SECRET_KEY:
        raise HTTPException(500, "Stripe not configured")
    package = CREDIT_PACKAGES.get(purchase.package)
    if not package:
        raise HTTPException(400, "Invalid package")
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': package['name'],
                        'description': f'{package["credits"]} BookieVerse Credits',
                    },
                    'unit_amount': package['amount'],
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"{os.getenv('APP_URL', 'https://bookieverse.onrender.com')}/app?payment=success",
            cancel_url=f"{os.getenv('APP_URL', 'https://bookieverse.onrender.com')}/app?payment=cancelled",
            client_reference_id=user_id,
            metadata={'user_id': user_id, 'package': purchase.package, 'credits': package['credits']}
        )
        return {"checkout_url": checkout_session.url}
    except Exception as e:
        raise HTTPException(500, f"Error creating checkout: {str(e)}")

@app.post("/api/shop/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "Webhook secret not configured")
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {str(e)}")
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session['metadata']['user_id']
        credits = int(session['metadata']['credits'])
        package = session['metadata']['package']
        user = users_db.get(user_id)
        if user:
            user['balance'] += credits
            user['total_purchased'] = user.get('total_purchased', 0) + credits
            purchase_id = f"purchase_{len(purchases_db) + 1}"
            purchases_db[purchase_id] = {
                "id": purchase_id, "user_id": user_id, "package": package, "credits": credits,
                "amount_paid": session['amount_total'] / 100, "stripe_session_id": session['id'],
                "created_at": datetime.utcnow().isoformat()
            }
    return {"status": "success"}

@app.get("/api/shop/purchases")
def get_purchases(token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user_purchases = [p for p in purchases_db.values() if p["user_id"] == user_id]
    user_purchases.sort(key=lambda x: x["created_at"], reverse=True)
    return user_purchases

@app.get("/api/leaderboard")
def leaderboard():
    sorted_users = sorted(users_db.values(), key=lambda x: x["profit"], reverse=True)
    return sorted_users[:10]

@app.get("/api/user")
def get_user(token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    apply_hourly_currency(user_id)
    user = users_db[user_id]
    now = datetime.utcnow()
    last_accrual = user.get("last_accrual", now)
    seconds_until_next = 3600 - ((now - last_accrual).total_seconds() % 3600)
    following_count = len([f for f in follows_db.values() if f["user_id"] == user_id])
    return {
        "id": user["id"], "username": user["username"], "balance": user["balance"],
        "profit": user["profit"], "wins": user["wins"], "losses": user["losses"],
        "lines_created": user.get("lines_created", 0), "total_earned": user.get("total_earned", 0),
        "total_purchased": user.get("total_purchased", 0), "hourly_rate": HOURLY_CURRENCY,
        "next_drop_seconds": int(seconds_until_next), "groups": user.get("groups", []),
        "following": following_count
    }

@app.get("/app", response_class=HTMLResponse)
def serve_app():
    with open("index.html", "r") as f:
        return f.read()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
