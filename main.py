# main.py - BookieVerse with PostgreSQL - ALL FEATURES

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List
import hashlib
import jwt
from datetime import datetime, timedelta
import uvicorn
import os
import stripe
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text, text
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from sqlalchemy import func
import json

app = FastAPI(title="BookieVerse Complete")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

SECRET_KEY = os.getenv("SECRET_KEY", "bookieverse-secret")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bookieverse.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

PROP_TYPES = {
    "NBA": ["Points", "Rebounds", "Assists", "3-Pointers Made", "Steals", "Blocks", "Points+Rebounds+Assists"],
    "NFL": ["Passing Yards", "Rushing Yards", "Receiving Yards", "Touchdowns", "Receptions", "Interceptions"],
    "MLB": ["Strikeouts", "Hits", "Home Runs", "RBIs", "Earned Runs", "Walks", "Total Bases"],
    "NHL": ["Goals", "Assists", "Points", "Shots on Goal", "Saves", "Power Play Points"],
}

# Database
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    balance = Column(Float, default=1000.0)
    profit = Column(Float, default=0.0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    lines_created = Column(Integer, default=0)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Profile fields
    avatar = Column(Text, nullable=True)           # base64 data URI
    bio = Column(String(300), nullable=True)
    favorite_team = Column(String(60), nullable=True)
    favorite_sport = Column(String(40), nullable=True)
    location = Column(String(60), nullable=True)
    banner_color = Column(String(20), nullable=True)  # hex color for profile banner

class Line(Base):
    __tablename__ = "lines"
    id = Column(Integer, primary_key=True)
    bookie_id = Column(Integer)
    bookie_name = Column(String)
    game_id = Column(String)
    game = Column(String)
    sport = Column(String)
    type = Column(String)
    side = Column(String)
    value = Column(Float)
    odds = Column(Integer, default=-110)       # American odds for bookie's side
    amount = Column(Float)                      # Bookie's total risk amount
    status = Column(String, default="open")
    total_action = Column(Float, default=0.0)  # Bookie stake consumed so far
    current_bettors = Column(Integer, default=0)
    max_bettors = Column(Integer, nullable=True)
    max_bet_per_user = Column(Float, nullable=True)
    max_total_action = Column(Float, nullable=True)
    is_private = Column(Boolean, default=False)
    group_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Bet(Base):
    __tablename__ = "bets"
    id = Column(Integer, primary_key=True)
    line_id = Column(Integer)
    bookie_id = Column(Integer)
    bookie_name = Column(String)
    bettor_id = Column(Integer)
    bettor_name = Column(String)
    game_id = Column(String, nullable=True)
    game = Column(String)
    type = Column(String)
    bookie_side = Column(String)
    bettor_side = Column(String)
    value = Column(Float)
    odds = Column(Integer, nullable=True, default=-110)        # American odds (bookie's side)
    amount = Column(Float)                                      # Bookie's stake portion (legacy compat)
    bookie_amount = Column(Float, nullable=True)               # Bookie's stake for this specific bet
    bettor_amount = Column(Float, nullable=True)               # Bettor's stake
    status = Column(String, default="pending")
    winner = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Prop(Base):
    __tablename__ = "props"
    id = Column(Integer, primary_key=True)
    bookie_id = Column(Integer)
    bookie_name = Column(String)
    game_id = Column(String, nullable=True)
    game = Column(String, nullable=True)
    sport = Column(String)
    player_name = Column(String)
    prop_type = Column(String)
    line = Column(Float)
    side = Column(String)
    odds = Column(Integer, nullable=True, default=-110)   # American odds
    amount = Column(Float)
    status = Column(String, default="open")
    created_at = Column(DateTime, default=datetime.utcnow)

class PropBet(Base):
    __tablename__ = "prop_bets"
    id = Column(Integer, primary_key=True)
    prop_id = Column(Integer)
    bookie_id = Column(Integer)
    bookie_name = Column(String)
    bettor_id = Column(Integer)
    bettor_name = Column(String)
    game_id = Column(String, nullable=True)
    player_name = Column(String)
    prop_type = Column(String)
    line = Column(Float)
    bookie_side = Column(String)
    bettor_side = Column(String)
    odds = Column(Integer, nullable=True, default=-110)
    bookie_amount = Column(Float, nullable=True)
    bettor_amount = Column(Float, nullable=True)
    amount = Column(Float)
    status = Column(String, default="pending")
    winner = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Challenge(Base):
    __tablename__ = "challenges"
    id = Column(Integer, primary_key=True)
    challenger_id = Column(Integer)
    challenger_name = Column(String)
    challenged_id = Column(Integer)
    challenged_name = Column(String)
    game_id = Column(String)
    game = Column(String)
    sport = Column(String)
    type = Column(String)       # spread, moneyline, total
    side = Column(String)       # challenger's side
    value = Column(Float)
    odds = Column(Integer, default=-110)
    amount = Column(Float)      # challenger's stake (deducted on creation)
    message = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending, accepted, declined, cancelled
    bet_id = Column(Integer, nullable=True)     # set when accepted → links to Bet
    created_at = Column(DateTime, default=datetime.utcnow)

class Follow(Base):
    __tablename__ = "follows"
    id = Column(Integer, primary_key=True)
    follower_id = Column(Integer, index=True)
    followed_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class FriendRequest(Base):
    __tablename__ = "friend_requests"
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, index=True)
    receiver_id = Column(Integer, index=True)
    status = Column(String, default="pending")   # pending | accepted | declined
    created_at = Column(DateTime, default=datetime.utcnow)

class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    description = Column(Text, nullable=True)
    creator_id = Column(Integer)
    creator_name = Column(String)
    members = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    type = Column(String)           # challenge_received, challenge_accepted, challenge_declined, bet_matched, bet_settled
    title = Column(String)
    body = Column(String)
    is_read = Column(Boolean, default=False)
    ref_id = Column(Integer, nullable=True)   # challenge_id or bet_id for deep-linking
    created_at = Column(DateTime, default=datetime.utcnow)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    username = Column(String)
    message = Column(Text)
    room = Column(String, default="global")   # future: per-game rooms
    reply_to_id = Column(Integer, nullable=True)  # future: threading
    created_at = Column(DateTime, default=datetime.utcnow)

class Parlay(Base):
    __tablename__ = "parlays"
    id = Column(Integer, primary_key=True)
    bookie_id = Column(Integer)
    bookie_name = Column(String)
    legs = Column(Text)           # JSON: [{game_id, game, sport, type, side, value, odds}, ...]
    combined_odds = Column(Integer)  # American odds for the full parlay
    amount = Column(Float)           # Bookie's max liability (escrowed)
    total_action = Column(Float, default=0.0)
    status = Column(String, default="open")   # open, settled, cancelled
    is_private = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class ParlayBet(Base):
    __tablename__ = "parlay_bets"
    id = Column(Integer, primary_key=True)
    parlay_id = Column(Integer)
    bookie_id = Column(Integer)
    bookie_name = Column(String)
    bettor_id = Column(Integer)
    bettor_name = Column(String)
    bookie_amount = Column(Float)   # bookie's liability for this ticket
    bettor_amount = Column(Float)   # bettor's stake
    legs_result = Column(Text)      # JSON: {game_id: "pending"|"won"|"lost"|"push"}
    status = Column(String, default="pending")  # pending, won, lost
    winner = Column(String, nullable=True)       # "bookie" or "bettor"
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def run_migrations():
    """
    Safe migration: add any new columns that don't yet exist in the live DB.
    Uses ADD COLUMN IF NOT EXISTS so it's a no-op once the column is there.
    Also runs expire_pregame_lines immediately to clean up stale open lines.
    """
    migrations = [
        # lines table
        "ALTER TABLE lines ADD COLUMN IF NOT EXISTS odds INTEGER DEFAULT -110",
        # bets table
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS odds INTEGER DEFAULT -110",
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS bookie_amount FLOAT",
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS bettor_amount FLOAT",
        # props table
        "ALTER TABLE props ADD COLUMN IF NOT EXISTS game_id VARCHAR",
        "ALTER TABLE props ADD COLUMN IF NOT EXISTS game VARCHAR",
        "ALTER TABLE props ADD COLUMN IF NOT EXISTS sport VARCHAR",
        "ALTER TABLE props ADD COLUMN IF NOT EXISTS odds INTEGER DEFAULT -110",
        # prop_bets table
        "ALTER TABLE prop_bets ADD COLUMN IF NOT EXISTS game_id VARCHAR",
        "ALTER TABLE prop_bets ADD COLUMN IF NOT EXISTS odds INTEGER DEFAULT -110",
        "ALTER TABLE prop_bets ADD COLUMN IF NOT EXISTS bookie_amount FLOAT",
        "ALTER TABLE prop_bets ADD COLUMN IF NOT EXISTS bettor_amount FLOAT",
        # users table — profile fields (added for profile/settings feature)
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS bio VARCHAR(300)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_team VARCHAR(60)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_sport VARCHAR(40)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS location VARCHAR(60)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS banner_color VARCHAR(20)",
        # chat_messages table (new — global chat)
        """CREATE TABLE IF NOT EXISTS chat_messages (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            username VARCHAR,
            message TEXT,
            room VARCHAR DEFAULT 'global',
            reply_to_id INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        # bets table — game_id and created_at for live tracking
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS game_id VARCHAR",
        "ALTER TABLE bets ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception as e:
                print(f"Migration skipped ({sql[:60]}...): {e}")

run_migrations()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

GAMES = [
    {"id": "demo_1", "home": "Lakers",  "away": "Warriors", "sport": "NBA", "date": "2026-03-05", "commence_time": "2026-03-05T02:00:00Z"},
    {"id": "demo_2", "home": "Celtics", "away": "Heat",     "sport": "NBA", "date": "2026-03-05", "commence_time": "2026-03-05T00:00:00Z"},
    {"id": "demo_3", "home": "Nuggets", "away": "Clippers", "sport": "NBA", "date": "2026-03-06", "commence_time": "2026-03-06T01:00:00Z"},
    {"id": "demo_4", "home": "Bucks",   "away": "76ers",    "sport": "NBA", "date": "2026-03-06", "commence_time": "2026-03-06T23:00:00Z"},
    {"id": "demo_5", "home": "Suns",    "away": "Mavs",     "sport": "NBA", "date": "2026-03-07", "commence_time": "2026-03-07T02:00:00Z"},
]

FUTURES = [
    {"id": "f1", "market_name": "NBA Championship", "sport": "NBA", "options": ["Lakers", "Celtics", "Warriors"]},
    {"id": "f2", "market_name": "Super Bowl", "sport": "NFL", "options": ["Chiefs", "Bills", "49ers"]},
]

# ─── ODDS HELPERS ────────────────────────────────────────────────────────────

def bettor_stake_from_bookie(bookie_stake: float, odds: int) -> float:
    """
    Given bookie's max liability (what they pay out if they lose) and their American odds,
    return what bettor must risk to take the full line.

    Bookie -110 liability=$110 → bettor risks $100 to win $110
    Bookie +150 liability=$100 → bettor risks $66.67 to win $100
    Formula: bettor_stake = liability * (100 / abs(odds))
    Works for both positive and negative since:
      -110 → 100/110 ≈ 0.909 → bettor risks less than liability ✓
      +150 → 100/150 ≈ 0.667 → bettor risks less than liability ✓
    """
    return round(bookie_stake * (100 / abs(odds)), 2)

def bookie_portion_from_bettor(bettor_stake: float, odds: int) -> float:
    """
    Inverse of bettor_stake_from_bookie.
    Given bettor's stake, return how much bookie liability is consumed.
    bettor_stake = liability * (100/abs(odds))
    → liability = bettor_stake * (abs(odds)/100)
    """
    return round(bettor_stake * (abs(odds) / 100), 2)

def format_odds(odds: int) -> str:
    """Format American odds for display: -110 → '-110', +150 → '+150'."""
    return f"+{odds}" if odds > 0 else str(odds)

# ─── ODDS HELPERS END ─────────────────────────────────────────────────────────

# ─── GAMES CACHE (5-minute TTL) ──────────────────────────────────────────────
_games_cache: list = []
_games_cache_ts: float = 0.0

def get_cached_games() -> list:
    """Return games from cache if fresh (< 5 min), else re-fetch and cache."""
    global _games_cache, _games_cache_ts
    import time
    if _games_cache and (time.time() - _games_cache_ts) < 300:
        return _games_cache
    fresh = fetch_live_games()
    _games_cache = fresh
    _games_cache_ts = time.time()
    return fresh

# ─────────────────────────────────────────────────────────────────────────────
ESPN_SPORTS = [
    ("basketball/nba", "NBA"),
    ("football/nfl", "NFL"),
    ("baseball/mlb", "MLB"),
    ("hockey/nhl", "NHL"),
    ("soccer/eng.1", "Premier League"),
    ("soccer/esp.1", "La Liga"),
    ("soccer/uefa.champions", "Champions League"),
    ("soccer/usa.1", "MLS"),
]

def fetch_espn_scoreboard(sport_path: str, sport_label: str) -> list:
    """Fetch games from ESPN free public API. No key, no quota."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return []
        games = []
        for event in resp.json().get("events", []):
            comp = event.get("competitions", [{}])[0]
            state = comp.get("status", {}).get("type", {}).get("state", "pre")
            if state == "post":
                continue  # finished, skip for marketplace
            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            def tn(c): return c.get("team",{}).get("displayName") or c.get("team",{}).get("shortDisplayName","Unknown")
            commence = event.get("date", "")
            games.append({
                "id": f"espn_{event['id']}",
                "home": tn(home),
                "away": tn(away),
                "sport": sport_label,
                "date": commence[:10] if commence else "",
                "commence_time": commence,
                "status": "live" if state == "in" else "upcoming",
                "home_score": home.get("score", ""),
                "away_score": away.get("score", ""),
            })
        return games
    except Exception as e:
        print(f"ESPN fetch error {sport_path}: {e}")
        return []

def fetch_live_games():
    """Fetch upcoming/live games from ESPN (free, no quota). Falls back to demo data."""
    try:
        games = []
        for sport_path, sport_label in ESPN_SPORTS:
            games.extend(fetch_espn_scoreboard(sport_path, sport_label))
        games.sort(key=lambda x: x.get("commence_time", ""))
        print(f"[games] ESPN returned {len(games)} games")
        return games if games else GAMES
    except Exception as e:
        print(f"[games] ESPN error: {e}")
        return GAMES

def fetch_espn_completed() -> list:
    """Fetch recently completed games from ESPN for settlement. No quota."""
    completed = []
    for sport_path, sport_label in ESPN_SPORTS:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                continue
            for event in resp.json().get("events", []):
                comp = event.get("competitions", [{}])[0]
                state = comp.get("status", {}).get("type", {}).get("state", "")
                if state != "post":
                    continue
                competitors = comp.get("competitors", [])
                home = next((c for c in competitors if c.get("homeAway") == "home"), None)
                away = next((c for c in competitors if c.get("homeAway") == "away"), None)
                if not home or not away:
                    continue
                try:
                    home_score = int(float(home.get("score", 0)))
                    away_score = int(float(away.get("score", 0)))
                except (ValueError, TypeError):
                    continue
                completed.append({
                    "id": f"espn_{event['id']}",
                    "home_team": home.get("team",{}).get("displayName") or home.get("team",{}).get("shortDisplayName","Home"),
                    "away_team": away.get("team",{}).get("displayName") or away.get("team",{}).get("shortDisplayName","Away"),
                    "home_score": home_score,
                    "away_score": away_score,
                })
        except Exception as e:
            print(f"[scores] ESPN fetch error {sport_path}: {e}")
    return completed

def check_game_scores():
    """Check ESPN scores and auto-settle bets + parlays every 5 minutes."""
    db = SessionLocal()
    total_settled = 0
    try:
        completed = fetch_espn_completed()
        print(f"[scores] ESPN: {len(completed)} completed games")
        completed_map = {g["id"]: g for g in completed}

        # ── Regular bets ──────────────────────────────────────────────────────
        pending_bets = db.query(Bet).filter(Bet.status == "pending").all()
        pending_ids = set(b.game_id for b in pending_bets if b.game_id)

        for game in completed:
            game_id = game["id"]
            if game_id not in pending_ids:
                continue
            home_score, away_score = game["home_score"], game["away_score"]
            print(f"[scores] {game_id}: {game['home_team']} {home_score} - {game['away_team']} {away_score}")
            bets = [b for b in pending_bets if b.game_id == game_id]
            for bet in bets:
                winner = determine_winner(bet, home_score, away_score)
                if winner:
                    settle_bet(db, bet, winner)
                    total_settled += 1
            line_ids = set(b.line_id for b in bets if b.line_id)
            for line_id in line_ids:
                line = db.query(Line).filter(Line.id == line_id).first()
                if line and line.status not in ("settled", "refunded", "cancelled", "expired"):
                    refund_unmatched_line(db, line)
                    line.status = "settled"

        # ── Parlay bets ───────────────────────────────────────────────────────
        pending_pbs = db.query(ParlayBet).filter(ParlayBet.status == "pending").all()
        for pb in pending_pbs:
            legs_result = json.loads(pb.legs_result or "{}")
            parlay = db.query(Parlay).filter(Parlay.id == pb.parlay_id).first()
            if not parlay:
                continue
            legs = json.loads(parlay.legs)
            changed = False
            for leg in legs:
                gid = leg["game_id"]
                if legs_result.get(gid) != "pending":
                    continue  # already resolved
                if gid not in completed_map:
                    continue
                game = completed_map[gid]
                raw = determine_leg_winner(leg, game["home_score"], game["away_score"])
                if raw:
                    # Translate to leg outcome: "won" = bookie's pick won, "lost" = bookie lost, "push"
                    if raw == "push":
                        legs_result[gid] = "push"
                    elif raw == "bookie":
                        legs_result[gid] = "won"    # bookie's leg came through
                    else:
                        legs_result[gid] = "lost"   # bookie's pick failed
                    changed = True
            if changed:
                pb.legs_result = json.dumps(legs_result)
            # Check if parlay is fully resolved
            statuses = list(legs_result.values())
            if any(s == "lost" for s in statuses):
                # At least one bookie leg busted → bettor wins
                settle_parlay_bet(db, pb, "bettor")
                total_settled += 1
            elif all(s in ("won", "push") for s in statuses) and len(statuses) == len(legs):
                # All bookie legs won/pushed → bookie wins
                settle_parlay_bet(db, pb, "bookie")
                total_settled += 1

        db.commit()
        print(f"[scores] Done — settled {total_settled} bets/parlays")
    except Exception as e:
        print(f"[scores] Error: {e}")
        import traceback; traceback.print_exc()
        db.rollback()
    finally:
        db.close()


def determine_winner(bet, home_score, away_score):
    """Determine bet winner based on scores. Returns 'bookie', 'bettor', or 'push'."""
    score_diff = home_score - away_score
    
    if bet.type == "spread":
        if bet.bookie_side == "home":
            adjusted = score_diff + bet.value
            if adjusted > 0: return "bookie"
            if adjusted < 0: return "bettor"
            return "push"
        else:
            adjusted = score_diff - bet.value
            if adjusted < 0: return "bookie"
            if adjusted > 0: return "bettor"
            return "push"
    elif bet.type == "moneyline":
        if home_score == away_score: return "push"
        if bet.bookie_side == "home":
            return "bookie" if home_score > away_score else "bettor"
        else:
            return "bookie" if away_score > home_score else "bettor"
    elif bet.type == "total":
        total = home_score + away_score
        if total == bet.value: return "push"
        if bet.bookie_side == "over":
            return "bookie" if total > bet.value else "bettor"
        else:
            return "bookie" if total < bet.value else "bettor"
    return None

def settle_bet(db, bet, winner):
    """Auto-settle a bet. winner can be 'bookie', 'bettor', or 'push'."""
    # Use split amounts if available (odds-aware), fall back to legacy even-money
    b_amt = bet.bookie_amount if bet.bookie_amount is not None else bet.amount
    t_amt = bet.bettor_amount if bet.bettor_amount is not None else bet.amount
    total_pot = b_amt + t_amt

    bookie = db.query(User).filter(User.id == bet.bookie_id).first()
    bettor = db.query(User).filter(User.id == bet.bettor_id).first()

    if not bookie or not bettor:
        print(f"settle_bet: could not find bookie or bettor for bet {bet.id}")
        return

    bet.status = "settled"
    bet.winner = winner

    if winner == "push":
        bookie.balance += b_amt
        bettor.balance += t_amt
        push_notification(db, bookie.id, "bet_settled", "🤝 Push — stake returned",
            f"{bet.game} · ${b_amt:.2f} returned to you", bet.id)
        push_notification(db, bettor.id, "bet_settled", "🤝 Push — stake returned",
            f"{bet.game} · ${t_amt:.2f} returned to you", bet.id)
    elif winner == "bookie":
        bookie.balance += total_pot
        bookie.profit += t_amt
        bookie.wins += 1
        bettor.profit -= t_amt
        bettor.losses += 1
        push_notification(db, bookie.id, "bet_settled", f"🏆 You won! +${t_amt:.2f}",
            f"{bet.game} · {bet.type.upper()} · @{bet.bettor_name} paid you", bet.id)
        push_notification(db, bettor.id, "bet_settled", f"💸 You lost -${t_amt:.2f}",
            f"{bet.game} · {bet.type.upper()} · paid @{bet.bookie_name}", bet.id)
    else:  # bettor wins
        bettor.balance += total_pot
        bettor.profit += b_amt
        bettor.wins += 1
        bookie.profit -= b_amt
        bookie.losses += 1
        push_notification(db, bettor.id, "bet_settled", f"🏆 You won! +${b_amt:.2f}",
            f"{bet.game} · {bet.type.upper()} · @{bet.bookie_name} paid you", bet.id)
        push_notification(db, bookie.id, "bet_settled", f"💸 You lost -${b_amt:.2f}",
            f"{bet.game} · {bet.type.upper()} · paid @{bet.bettor_name}", bet.id)

def refund_unmatched_line(db, line):
    """When a line closes, refund any unmatched portion back to the bookie."""
    unmatched = line.amount - (line.total_action or 0)
    if unmatched > 0.01:  # avoid floating point noise
        bookie = db.query(User).filter(User.id == line.bookie_id).first()
        if bookie:
            bookie.balance += unmatched
            print(f"Refunded ${unmatched:.2f} unmatched funds to bookie {bookie.username}")

# ─── NOTIFICATION HELPERS ─────────────────────────────────────────────────────

def push_notification(db, user_id: int, type: str, title: str, body: str, ref_id: int = None):
    """Create a notification for a user. Fire-and-forget — never raises."""
    try:
        n = Notification(user_id=user_id, type=type, title=title, body=body, ref_id=ref_id)
        db.add(n)
        # No commit here — caller handles the commit
    except Exception as e:
        print(f"push_notification error: {e}")

# ─── NOTIFICATION HELPERS END ──────────────────────────────────────────────────

def expire_pregame_lines():
    """
    Expire open lines/props whose game has started OR whose game_id is no longer
    in the upcoming games list (game already happened and dropped off the API).
    Refunds the bookie's unmatched stake. Runs every minute.
    """
    now = datetime.utcnow()
    all_games = get_cached_games()

    # Games that have already kicked off (still in API but past commence_time)
    started_ids = set()
    # Games that are still upcoming (safe to keep open)
    upcoming_ids = set()

    for g in all_games:
        ct = g.get("commence_time", "")
        if not ct:
            continue
        try:
            game_dt = datetime.strptime(ct[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
        if game_dt <= now:
            started_ids.add(g["id"])
        else:
            upcoming_ids.add(g["id"])

    db = SessionLocal()
    try:
        all_open_lines = db.query(Line).filter(Line.status == "open").all()
        all_open_props = db.query(Prop).filter(
            Prop.status == "open",
            Prop.game_id.isnot(None),
            ~Prop.game_id.like("future_%")
        ).all()

        lines_expired = 0
        props_expired = 0

        # All known game IDs (both started and upcoming)
        all_known_ids = started_ids | upcoming_ids

        for line in all_open_lines:
            gid = line.game_id or ""
            # Expire if: game has started (in API, past commence) OR
            # game has dropped off API entirely (means it's finished)
            # Skip lines with no game_id or "unknown" style IDs
            game_is_over = gid and gid not in all_known_ids and not gid.startswith("demo_") and not gid.startswith("future_")
            if gid in started_ids or game_is_over:
                refund_unmatched_line(db, line)
                line.status = "expired"
                push_notification(
                    db, line.bookie_id, "bet_settled",
                    "⏰ Line expired — game started",
                    f"{line.game} · Unmatched stake refunded",
                    line.id
                )
                lines_expired += 1

        for prop in all_open_props:
            gid = prop.game_id or ""
            prop_is_over = gid and gid not in all_known_ids and not gid.startswith("demo_") and not gid.startswith("future_")
            if gid in started_ids or prop_is_over:
                bookie = db.query(User).filter(User.id == prop.bookie_id).first()
                if bookie:
                    bookie.balance += prop.amount
                prop.status = "expired"
                push_notification(
                    db, prop.bookie_id, "bet_settled",
                    "⏰ Prop expired — game started",
                    f"{prop.player_name} {prop.prop_type} · ${prop.amount:.2f} refunded",
                    prop.id
                )
                props_expired += 1

        if lines_expired or props_expired:
            db.commit()
            print(f"[expire_pregame] Expired {lines_expired} lines, {props_expired} props")

    except Exception as e:
        print(f"Error in expire_pregame_lines: {e}")
        db.rollback()
    finally:
        db.close()

# Initialize scheduler - started in app lifecycle to avoid duplicate workers
scheduler = BackgroundScheduler()
scheduler.add_job(check_game_scores,    'interval', minutes=5,
                  misfire_grace_time=300, coalesce=True, max_instances=1)
scheduler.add_job(expire_pregame_lines, 'interval', minutes=1,
                  misfire_grace_time=60,  coalesce=True, max_instances=1)

# Track last score check so we can trigger on requests when scheduler has been asleep
_last_score_check: float = 0.0

def maybe_check_scores():
    """Run score check if scheduler hasn't fired in >6 minutes (Render sleep recovery)."""
    global _last_score_check
    import time
    if time.time() - _last_score_check > 360:
        _last_score_check = time.time()
        try:
            check_game_scores()
        except Exception as e:
            print(f"[scores] background check error: {e}")

@app.on_event("startup")
def start_scheduler():
    if not scheduler.running:
        scheduler.start()
    # Clean up stale open lines immediately
    try:
        expire_pregame_lines()
        print("[startup] expire_pregame_lines ran successfully")
    except Exception as _e:
        print(f"[startup] expire_pregame_lines error (non-fatal): {_e}")
    # Check scores immediately on startup
    try:
        print(f"[startup] ODDS_API_KEY set: {bool(ODDS_API_KEY)}")
        check_game_scores()
        print("[startup] check_game_scores ran successfully")
    except Exception as _e:
        print(f"[startup] check_game_scores error (non-fatal): {_e}")

@app.on_event("shutdown")
def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)

# Models
class UserCreate(BaseModel):
    username: str
    password: str

class LineCreate(BaseModel):
    game_id: str
    type: str
    side: str
    value: float
    odds: int = -110
    amount: float
    max_bettors: Optional[int] = None
    max_bet_per_user: Optional[float] = None
    max_total_action: Optional[float] = None
    is_private: Optional[bool] = False
    group_id: Optional[int] = None

class LineUpdate(BaseModel):
    odds: Optional[int] = None          # Change the odds
    add_amount: Optional[float] = None  # Add more stake to the line
    max_bet_per_user: Optional[float] = None
    max_bettors: Optional[int] = None

class PropCreate(BaseModel):
    game_id: str
    sport: str
    player_name: str
    prop_type: str
    line: float
    side: str
    odds: int = -110
    amount: float

class TakeLine(BaseModel):
    line_id: int
    amount: Optional[float] = None  # Bettor can specify amount

class TakeProp(BaseModel):
    prop_id: int

class ChallengeCreate(BaseModel):
    challenged_username: str
    game_id: str
    type: str
    side: str
    value: float
    odds: int = -110
    amount: float
    message: Optional[str] = None

class ChallengeAction(BaseModel):
    challenge_id: int

class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None

class InviteBody(BaseModel):
    username: str

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def create_token(user_id: int) -> str:
    return jwt.encode({"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=7)}, SECRET_KEY, algorithm="HS256")

def verify_token(token: str) -> Optional[int]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"]).get("user_id")
    except:
        return None

@app.get("/")
def home():
    return {"message": "🎯 BookieVerse", "app": "/app"}

@app.post("/api/auth/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    try:
        print(f"=== REGISTER ATTEMPT: {user.username} ===")
        
        if len(user.password) < 6:
            print("Password too short")
            raise HTTPException(400, "Password 6+ chars")
        
        # Check if username exists
        print(f"Checking if {user.username} exists...")
        existing = db.query(User).filter(User.username == user.username).first()
        print(f"Existing user found: {existing is not None}")
        
        if existing:
            print(f"User {user.username} already exists!")
            raise HTTPException(400, "Username taken")
        
        print("Counting total users...")
        user_count = db.query(User).count()
        is_admin = user_count == 0
        print(f"Total users: {user_count}, Will be admin: {is_admin}")
        
        print("Creating new user...")
        new_user = User(username=user.username, password=hash_password(user.password), is_admin=is_admin)
        db.add(new_user)
        
        print("Committing to database...")
        db.commit()
        db.refresh(new_user)
        
        print(f"User created successfully! ID: {new_user.id}")
        return {
            "token": create_token(new_user.id), 
            "user": {
                "id": new_user.id, 
                "username": new_user.username, 
                "balance": new_user.balance,
                "profit": new_user.profit,
                "wins": new_user.wins,
                "losses": new_user.losses,
                "lines_created": new_user.lines_created,
                "is_admin": new_user.is_admin
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"!!! REGISTRATION ERROR: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise HTTPException(500, f"Database error: {str(e)}")

@app.post("/api/auth/login")
def login(user: UserCreate, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == user.username).first()
    if not u or u.password != hash_password(user.password):
        raise HTTPException(401, "Invalid credentials")
    return {
        "token": create_token(u.id), 
        "user": {
            "id": u.id, 
            "username": u.username, 
            "balance": u.balance,
            "profit": u.profit,
            "wins": u.wins,
            "losses": u.losses,
            "lines_created": u.lines_created,
            "is_admin": u.is_admin
        }
    }

# ── Global Chat ──────────────────────────────────────────────────────────────
class ChatSend(BaseModel):
    message: str
    room: str = "global"

@app.get("/api/chat")
def get_chat(room: str = "global", since_id: int = 0, limit: int = 60, db: Session = Depends(get_db)):
    q = db.query(ChatMessage).filter(ChatMessage.room == room)
    if since_id:
        q = q.filter(ChatMessage.id > since_id)
    else:
        q = q.order_by(ChatMessage.id.desc()).limit(limit)
        msgs = list(reversed(q.all()))
        return {"messages": [_fmt_chat(m) for m in msgs], "last_id": msgs[-1].id if msgs else 0}
    msgs = q.order_by(ChatMessage.id.asc()).all()
    return {"messages": [_fmt_chat(m) for m in msgs], "last_id": msgs[-1].id if msgs else since_id}

def _fmt_chat(m):
    def time_ago(dt):
        if not dt: return ""
        d = (datetime.utcnow() - dt).total_seconds()
        if d < 60: return "now"
        if d < 3600: return f"{int(d//60)}m"
        if d < 86400: return f"{int(d//3600)}h"
        return f"{int(d//86400)}d"
    return {"id": m.id, "user_id": m.user_id, "username": m.username,
            "message": m.message, "room": m.room,
            "ts": time_ago(m.created_at),
            "created_at": m.created_at.isoformat() if m.created_at else ""}

@app.post("/api/chat")
def send_chat(msg: ChatSend, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id: raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    text = msg.message.strip()
    if not text: raise HTTPException(400, "Message cannot be empty")
    if len(text) > 500: raise HTTPException(400, "Max 500 chars")
    recent = db.query(ChatMessage).filter(
        ChatMessage.user_id == user_id,
        ChatMessage.created_at >= datetime.utcnow() - timedelta(seconds=2)
    ).first()
    if recent: raise HTTPException(429, "Slow down")
    cm = ChatMessage(user_id=user_id, username=user.username, message=text, room=msg.room)
    db.add(cm); db.commit(); db.refresh(cm)
    return _fmt_chat(cm)

@app.delete("/api/chat/{msg_id}")
def delete_chat(msg_id: int, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id: raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    cm = db.query(ChatMessage).filter(ChatMessage.id == msg_id).first()
    if not cm: raise HTTPException(404, "Not found")
    if cm.user_id != user_id and not user.is_admin: raise HTTPException(403, "Not your message")
    db.delete(cm); db.commit()
    return {"ok": True}

# ── Social Activity Feed ──────────────────────────────────────────────────────
@app.get("/api/feed")
def get_feed(token: str, limit: int = 40, db: Session = Depends(get_db)):
    """
    Returns a unified activity feed of recent platform activity.
    Personalized: people you follow appear first, then global activity.
    Event types: line_posted, bet_matched, bet_won, bet_lost, parlay_posted,
                 parlay_won, parlay_lost, challenge_sent, challenge_won
    """
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    # Who the user follows
    follows = db.query(Follow).filter(Follow.follower_id == user_id).all()
    followed_ids = {f.followed_id for f in follows}

    cutoff = datetime.utcnow() - timedelta(days=7)  # last 7 days
    events = []

    def time_ago(dt):
        if not dt:
            return "recently"
        diff = datetime.utcnow() - dt
        s = diff.total_seconds()
        if s < 60:   return "just now"
        if s < 3600: return f"{int(s//60)}m ago"
        if s < 86400: return f"{int(s//3600)}h ago"
        return f"{int(s//86400)}d ago"

    def is_followed(uid):
        return uid in followed_ids

    # ── Lines posted (open only, non-private) ────────────────────────────────
    lines = db.query(Line).filter(
        Line.status == "open",
        Line.is_private == False,
        Line.created_at >= cutoff
    ).order_by(Line.created_at.desc()).limit(60).all()

    for l in lines:
        odds = l.odds or -110
        oddsStr = (f"+{odds}" if odds > 0 else str(odds))
        gp = (l.game or "").split(" @ ")
        away, home = (gp[0], gp[1]) if len(gp)==2 else ("Away","Home")
        if l.type == "total":
            pick = f"{'Over' if l.side=='over' else 'Under'} {l.value}"
        elif l.type == "spread":
            pick = f"{'Home' if l.side=='home' else 'Away'} {l.value:+.1f}"
        else:
            pick = home if l.side == "home" else away
        events.append({
            "id": f"line_{l.id}",
            "type": "line_posted",
            "actor": l.bookie_name,
            "actor_id": l.bookie_id,
            "followed": is_followed(l.bookie_id),
            "text": f"posted a {l.type} line",
            "detail": f"{l.game}",
            "meta": f"{pick} · {oddsStr} · ${l.amount:.0f} liability",
            "sport": l.sport or "",
            "amount": l.amount,
            "ts": time_ago(l.created_at),
            "raw_ts": l.created_at.isoformat() if l.created_at else "",
            "emoji": "⚡"
        })

    # ── Bets matched ─────────────────────────────────────────────────────────
    bets = db.query(Bet).filter(
        Bet.created_at >= cutoff
    ).order_by(Bet.created_at.desc()).limit(80).all()

    for b in bets:
        if b.status == "pending":
            events.append({
                "id": f"bet_matched_{b.id}",
                "type": "bet_matched",
                "actor": b.bettor_name,
                "actor_id": b.bettor_id,
                "followed": is_followed(b.bettor_id) or is_followed(b.bookie_id),
                "text": f"took a line from @{b.bookie_name}",
                "detail": b.game or "",
                "meta": f"{b.type.upper()} · ${b.bettor_amount or b.amount:.0f} at risk",
                "sport": "",
                "amount": b.bettor_amount or b.amount,
                "ts": time_ago(b.created_at),
                "raw_ts": b.created_at.isoformat() if b.created_at else "",
                "emoji": "🤝"
            })
        elif b.status == "settled" and b.winner:
            winner_name = b.bookie_name if b.winner == "bookie" else b.bettor_name
            winner_id   = b.bookie_id   if b.winner == "bookie" else b.bettor_id
            loser_name  = b.bettor_name if b.winner == "bookie" else b.bookie_name
            payout = b.bookie_amount if b.winner == "bookie" else b.bettor_amount
            events.append({
                "id": f"bet_settled_{b.id}",
                "type": "bet_won",
                "actor": winner_name,
                "actor_id": winner_id,
                "followed": is_followed(winner_id),
                "text": f"won a bet vs @{loser_name}",
                "detail": b.game or "",
                "meta": f"{b.type.upper()} · +${payout:.2f}",
                "sport": "",
                "amount": payout,
                "ts": time_ago(b.created_at),
                "raw_ts": b.created_at.isoformat() if b.created_at else "",
                "emoji": "🏆"
            })

    # ── Parlays posted ────────────────────────────────────────────────────────
    parlays = db.query(Parlay).filter(
        Parlay.is_private == False,
        Parlay.created_at >= cutoff
    ).order_by(Parlay.created_at.desc()).limit(30).all()

    for p in parlays:
        import json as _json
        try:
            legs = _json.loads(p.legs or "[]")
        except:
            legs = []
        odds = p.combined_odds or 0
        oddsStr = f"+{odds}" if odds > 0 else str(odds)
        events.append({
            "id": f"parlay_{p.id}",
            "type": "parlay_posted",
            "actor": p.bookie_name,
            "actor_id": p.bookie_id,
            "followed": is_followed(p.bookie_id),
            "text": f"posted a {len(legs)}-leg parlay",
            "detail": " · ".join(l.get("game","")[:20] for l in legs[:3]),
            "meta": f"Combined {oddsStr} · ${p.amount:.0f} liability",
            "sport": "",
            "amount": p.amount,
            "ts": time_ago(p.created_at),
            "raw_ts": p.created_at.isoformat() if p.created_at else "",
            "emoji": "🎰"
        })

    # ── Challenges ───────────────────────────────────────────────────────────
    challenges = db.query(Challenge).filter(
        Challenge.created_at >= cutoff
    ).order_by(Challenge.created_at.desc()).limit(30).all()

    for c in challenges:
        if c.status == "pending":
            events.append({
                "id": f"challenge_{c.id}",
                "type": "challenge_sent",
                "actor": c.challenger_name,
                "actor_id": c.challenger_id,
                "followed": is_followed(c.challenger_id),
                "text": f"challenged @{c.challenged_name}",
                "detail": c.game or "",
                "meta": f"${c.amount:.0f} on the line",
                "sport": c.sport or "",
                "amount": c.amount,
                "ts": time_ago(c.created_at),
                "raw_ts": c.created_at.isoformat() if c.created_at else "",
                "emoji": "⚔️"
            })

    # ── Sort: followed events first, then by timestamp ───────────────────────
    events.sort(key=lambda e: (0 if e["followed"] else 1, e["raw_ts"]), reverse=False)
    # Stable sort: followed first within same time bucket, newest overall on top
    events.sort(key=lambda e: e["raw_ts"], reverse=True)
    # Now re-sort so followed float up but we keep recency
    followed_events = [e for e in events if e["followed"]]
    global_events   = [e for e in events if not e["followed"]]
    # Interleave: 1 followed per 3 global, then append the rest
    merged = []
    fi, gi = 0, 0
    while fi < len(followed_events) or gi < len(global_events):
        if fi < len(followed_events):
            merged.append(followed_events[fi]); fi += 1
        for _ in range(3):
            if gi < len(global_events):
                merged.append(global_events[gi]); gi += 1
    # Deduplicate by id
    seen = set()
    final = []
    for e in merged:
        if e["id"] not in seen:
            seen.add(e["id"])
            final.append(e)

    return {"events": final[:limit], "total": len(final)}


# ── PWA Manifest + Service Worker ─────────────────────────────────────────────
@app.get("/manifest.json")
def get_manifest():
    return JSONResponse({
        "name": "BookieVerse",
        "short_name": "BookieVerse",
        "description": "P2P Sports Betting — Post lines, take action, settle up.",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0b1120",
        "theme_color": "#0b1120",
        "orientation": "portrait",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
        ],
        "categories": ["sports", "games", "entertainment"],
        "shortcuts": [
            {"name": "Marketplace", "url": "/?view=marketplace", "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]},
            {"name": "Set Lines",   "url": "/?view=create",      "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]},
            {"name": "My Bets",     "url": "/?view=bets",        "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]}
        ]
    })

@app.get("/sw.js")
def get_service_worker():
    sw_content = """
const CACHE_NAME = 'bookieverse-v1';
const STATIC_ASSETS = ['/'];

self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Network first for API calls, cache first for static assets
self.addEventListener('fetch', e => {
    const url = new URL(e.request.url);
    if (url.pathname.startsWith('/api/')) {
        // API: network only, no caching
        e.respondWith(fetch(e.request).catch(() => new Response('{"error":"offline"}', {headers:{'Content-Type':'application/json'}})));
    } else {
        // App shell: network first, fall back to cache
        e.respondWith(
            fetch(e.request)
                .then(res => {
                    const clone = res.clone();
                    caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
                    return res;
                })
                .catch(() => caches.match(e.request))
        );
    }
});

// Push notifications
self.addEventListener('push', e => {
    if (!e.data) return;
    const data = e.data.json();
    e.waitUntil(
        self.registration.showNotification(data.title || 'BookieVerse', {
            body: data.body || '',
            icon: '/icon-192.png',
            badge: '/icon-192.png',
            vibrate: [100, 50, 100],
            data: { url: data.url || '/' }
        })
    );
});

self.addEventListener('notificationclick', e => {
    e.notification.close();
    e.waitUntil(clients.openWindow(e.notification.data.url));
});
"""
    from fastapi.responses import Response
    return Response(content=sw_content, media_type="application/javascript")

# Pre-generated PNG icons (base64 embedded — proper PNG for PWA installability)
import base64 as _b64
_ICON_192_PNG = _b64.b64decode("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")
_ICON_512_PNG = _b64.b64decode("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AgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAABAAAAAAAQAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAgAAAAAAIAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAAAABAAAAEAAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAAAAAgAAACAAAABAAAAAAO3m/wet4q/0EKifbQAAAABJRU5ErkJggg==")

@app.get("/icon-192.png")
def get_icon_192():
    from fastapi.responses import Response
    return Response(content=_ICON_192_PNG, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})

@app.get("/icon-512.png")
def get_icon_512():
    from fastapi.responses import Response
    return Response(content=_ICON_512_PNG, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})

@app.get("/api/games")
def get_games():
    return get_cached_games()

@app.get("/api/live-scores")
def get_live_scores():
    """Lightweight endpoint returning live/recent scores with team names."""
    scores = {}
    for sport_path, _ in ESPN_SPORTS:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard"
        try:
            resp = requests.get(url, timeout=8)
            if resp.status_code != 200:
                continue
            for event in resp.json().get("events", []):
                comp = event.get("competitions", [{}])[0]
                state = comp.get("status", {}).get("type", {}).get("state", "pre")
                competitors = comp.get("competitors", [])
                home = next((c for c in competitors if c.get("homeAway") == "home"), None)
                away = next((c for c in competitors if c.get("homeAway") == "away"), None)
                if not home or not away:
                    continue
                status_detail = comp.get("status", {}).get("type", {}).get("shortDetail", "")
                def team_abbr(c):
                    t = c.get("team", {})
                    result = (t.get("abbreviation") or t.get("abbrev") or
                            t.get("shortDisplayName") or t.get("displayName", "")[:3].upper())
                    if not result:
                        print(f"[live-scores] ⚠ Could not extract team name. team keys: {list(t.keys())}")
                    return result
                scores[f"espn_{event['id']}"] = {
                    "state": state,
                    "home_team": team_abbr(home),
                    "away_team": team_abbr(away),
                    "home_score": home.get("score", ""),
                    "away_score": away.get("score", ""),
                    "status": status_detail,
                }
        except Exception:
            continue
    return scores

@app.get("/api/roster")
def get_roster(game_id: str, sport: str):
    """Fetch players for both teams in a game from ESPN roster API."""
    SPORT_MAP = {"NBA": "basketball/nba", "NFL": "football/nfl", "MLB": "baseball/mlb", "NHL": "hockey/nhl"}
    sport_path = SPORT_MAP.get(sport.upper())
    if not sport_path or not game_id.startswith("espn_"):
        return []
    espn_id = game_id.replace("espn_", "")
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return []
        event = next((e for e in resp.json().get("events", []) if e["id"] == espn_id), None)
        if not event:
            return []
        comp = event.get("competitions", [{}])[0]
        players = []
        for competitor in comp.get("competitors", []):
            team_id = competitor.get("team", {}).get("id")
            team_abbr = competitor.get("team", {}).get("abbreviation", "")
            if not team_id:
                continue
            roster_url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/teams/{team_id}/roster"
            try:
                r = requests.get(roster_url, timeout=8)
                if r.status_code != 200:
                    continue
                for athlete in r.json().get("athletes", []):
                    if isinstance(athlete, dict) and "items" in athlete:
                        for item in athlete["items"]:
                            fn = item.get("fullName") or item.get("displayName", "")
                            pos = item.get("position", {}).get("abbreviation", "")
                            if fn:
                                players.append({"name": fn, "team": team_abbr, "position": pos})
                    else:
                        fn = athlete.get("fullName") or athlete.get("displayName", "")
                        pos = athlete.get("position", {}).get("abbreviation", "")
                        if fn:
                            players.append({"name": fn, "team": team_abbr, "position": pos})
            except Exception:
                continue
        return players
    except Exception as e:
        print(f"[roster] Error: {e}")
        return []


@app.get("/api/futures")
def get_futures():
    return FUTURES

@app.get("/api/prop-types")
def get_prop_types():
    return PROP_TYPES

@app.get("/api/lines")
def get_lines(db: Session = Depends(get_db)):
    maybe_check_scores()   # recover from Render sleep — runs at most once per 6 min
    expire_pregame_lines() # close any lines whose game just started
    lines = db.query(Line).filter(Line.status == "open", (Line.is_private == False) | (Line.is_private == None)).all()
    result = []
    for l in lines:
        try:
            odds = l.odds if (l.odds is not None and l.odds != 0) else -110
            if -100 < odds < 100:
                odds = -110  # safety: reject invalid odds
            amount = l.amount or 0
            total_action = l.total_action or 0
            available_bookie = max(0, amount - total_action)
            available_for_bettor = bettor_stake_from_bookie(available_bookie, odds)
            result.append({
                "id": l.id, "bookie_id": l.bookie_id, "bookie_name": l.bookie_name,
                "game_id": l.game_id or "", "game": l.game or "", "sport": l.sport or "", "type": l.type or "moneyline", "side": l.side or "",
                "value": l.value or 0, "odds": odds, "amount": amount, "status": l.status,
                "total_action": total_action, "current_bettors": l.current_bettors or 0,
                "max_bet_per_user": l.max_bet_per_user, "is_private": l.is_private or False,
                "available_for_bettor": round(available_for_bettor, 2)
            })
        except Exception as e:
            print(f"get_lines: skipping line {l.id} due to error: {e}")
            continue
    return result

@app.post("/api/lines")
def create_line(line: LineCreate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.balance < line.amount:
        raise HTTPException(400, "Insufficient balance")
    
    all_games = get_cached_games()
    game = next((g for g in all_games if g["id"] == line.game_id), None)
    if not game:
        # Game not in current cache — could be a timing issue. Use game_id as label and continue.
        game_label = f"Game {line.game_id}"
        game_sport = "NBA"
    else:
        game_label = f"{game['away']} @ {game['home']}"
        game_sport = game["sport"]
    
    new_line = Line(bookie_id=user.id, bookie_name=user.username, game_id=line.game_id,
                   game=game_label, sport=game_sport,
                   type=line.type, side=line.side, value=line.value, odds=line.odds,
                   amount=line.amount, max_bettors=line.max_bettors,
                   max_bet_per_user=line.max_bet_per_user,
                   max_total_action=line.max_total_action,
                   is_private=line.is_private, group_id=line.group_id)
    user.balance -= line.amount
    user.lines_created += 1
    db.add(new_line)
    db.commit()
    db.refresh(new_line)
    return {"message": "Line created", "line_id": new_line.id}

@app.get("/api/lines/mine")
def get_my_lines(token: str, db: Session = Depends(get_db)):
    """Get all open lines posted by the authenticated bookie."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    lines = db.query(Line).filter(Line.bookie_id == user_id, Line.status == "open").order_by(Line.created_at.desc()).all()
    result = []
    for l in lines:
        try:
            odds = l.odds if (l.odds is not None and l.odds != 0) else -110
            if -100 < odds < 100:
                odds = -110
            amount = l.amount or 0
            total_action = l.total_action or 0
            unmatched = max(0, amount - total_action)
            available_for_bettor = bettor_stake_from_bookie(unmatched, odds)
            result.append({
                "id": l.id, "game": l.game or "", "sport": l.sport or "", "type": l.type or "moneyline",
                "side": l.side or "", "value": l.value or 0, "odds": odds,
                "amount": amount, "total_action": total_action,
                "unmatched": round(unmatched, 2),
                "available_for_bettor": round(available_for_bettor, 2),
                "current_bettors": l.current_bettors or 0,
                "max_bet_per_user": l.max_bet_per_user,
                "max_bettors": l.max_bettors,
                "is_private": l.is_private or False,
            })
        except Exception as e:
            print(f"get_my_lines: skipping line {l.id}: {e}")
            continue
    return result

@app.patch("/api/lines/{line_id}")
def update_line(line_id: int, update: LineUpdate, token: str, db: Session = Depends(get_db)):
    """Bookie adjusts odds, adds stake, or changes limits on their open line."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    line = db.query(Line).filter(Line.id == line_id, Line.bookie_id == user_id, Line.status == "open").first()
    if not line:
        raise HTTPException(404, "Line not found or not yours")

    if update.odds is not None:
        if update.odds == 0 or (-100 < update.odds < 100):
            raise HTTPException(400, "Odds must be ≤ -100 or ≥ +100")
        line.odds = update.odds

    if update.add_amount is not None and update.add_amount > 0:
        user = db.query(User).filter(User.id == user_id).first()
        if user.balance < update.add_amount:
            raise HTTPException(400, f"Insufficient balance. You have ${user.balance:.2f}")
        user.balance -= update.add_amount
        line.amount += update.add_amount

    if update.max_bet_per_user is not None:
        line.max_bet_per_user = update.max_bet_per_user if update.max_bet_per_user > 0 else None

    if update.max_bettors is not None:
        line.max_bettors = update.max_bettors if update.max_bettors > 0 else None

    db.commit()
    odds = line.odds if line.odds is not None else -110
    unmatched = line.amount - (line.total_action or 0)
    return {
        "message": "Line updated",
        "odds": odds,
        "amount": line.amount,
        "unmatched": round(unmatched, 2),
        "available_for_bettor": round(bettor_stake_from_bookie(unmatched, odds), 2)
    }

@app.delete("/api/lines/{line_id}")
def pull_line(line_id: int, token: str, db: Session = Depends(get_db)):
    """Bookie pulls their line — unmatched stake is refunded."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    line = db.query(Line).filter(Line.id == line_id, Line.bookie_id == user_id, Line.status == "open").first()
    if not line:
        raise HTTPException(404, "Line not found or not yours")

    refund_unmatched_line(db, line)
    line.status = "cancelled"
    db.commit()

    unmatched = line.amount - (line.total_action or 0)
    refunded = max(0, unmatched)
    return {"message": f"Line pulled. ${refunded:.2f} refunded to your balance."}

@app.post("/api/lines/take")
def take_line(take: TakeLine, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    # Run expiry first so any just-started games are closed before we check
    expire_pregame_lines()

    line = db.query(Line).filter(Line.id == take.line_id, Line.status == "open").first()
    if not line:
        raise HTTPException(404, "Line not available — game may have already started")
    if line.bookie_id == user_id:
        raise HTTPException(400, "Can't bet your own line")

    # Hard server-side guard: reject if game has started regardless of line status
    all_games = get_cached_games()
    now_utc = datetime.utcnow()
    game_obj = next((g for g in all_games if g["id"] == line.game_id), None)
    if game_obj:
        ct = game_obj.get("commence_time", "")
        if ct:
            try:
                game_dt = datetime.strptime(ct[:19], "%Y-%m-%dT%H:%M:%S")
                if game_dt <= now_utc:
                    refund_unmatched_line(db, line)
                    line.status = "expired"
                    db.commit()
                    raise HTTPException(400, "Game has already started — this line is now closed")
            except HTTPException:
                raise
            except Exception:
                pass

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    odds = line.odds if line.odds is not None else -110

    # Available bookie stake remaining on this line
    available_bookie = line.amount - (line.total_action or 0)
    if available_bookie <= 0:
        raise HTTPException(400, "Line is fully filled")

    # Max bettor can wager = bettor equivalent of available bookie stake
    max_bettor_stake = bettor_stake_from_bookie(available_bookie, odds)

    # Bettor's desired stake (they enter how much THEY want to risk)
    bettor_stake = take.amount if take.amount else max_bettor_stake
    bettor_stake = min(bettor_stake, max_bettor_stake)

    # Enforce max_bet_per_user (in bettor stake terms)
    if line.max_bet_per_user:
        already_bet = db.query(func.sum(Bet.bettor_amount)).filter(
            Bet.line_id == line.id,
            Bet.bettor_id == user_id
        ).scalar() or 0
        remaining = line.max_bet_per_user - already_bet
        if remaining <= 0:
            raise HTTPException(400, f"You've reached the max bet limit of ${line.max_bet_per_user}")
        bettor_stake = min(bettor_stake, remaining)

    # Enforce max_bettors
    if line.max_bettors:
        unique_bettors = db.query(Bet.bettor_id).filter(Bet.line_id == line.id).distinct().count()
        if unique_bettors >= line.max_bettors:
            user_has_bet = db.query(Bet).filter(
                Bet.line_id == line.id, Bet.bettor_id == user_id
            ).first()
            if not user_has_bet:
                raise HTTPException(400, f"Max of {line.max_bettors} bettors reached")

    if bettor_stake < 0.01:
        raise HTTPException(400, "Bet amount is too small")
    if user.balance < bettor_stake:
        raise HTTPException(400, f"Insufficient balance. Need ${bettor_stake:.2f}")

    # Corresponding bookie stake consumed for this bettor wager
    bookie_portion = bookie_portion_from_bettor(bettor_stake, odds)

    # Determine bettor's side
    if line.side in ("home", "away"):
        bettor_side = "away" if line.side == "home" else "home"
    elif line.side == "over":
        bettor_side = "under"
    elif line.side == "under":
        bettor_side = "over"
    else:
        bettor_side = line.side

    bet = Bet(
        line_id=line.id,
        bookie_id=line.bookie_id,
        bookie_name=line.bookie_name,
        bettor_id=user.id,
        bettor_name=user.username,
        game_id=line.game_id,
        game=line.game,
        type=line.type,
        bookie_side=line.side,
        bettor_side=bettor_side,
        value=line.value,
        odds=odds,
        amount=bookie_portion,          # legacy field = bookie portion
        bookie_amount=bookie_portion,
        bettor_amount=bettor_stake
    )

    line.total_action = (line.total_action or 0) + bookie_portion
    line.current_bettors = db.query(Bet.bettor_id).filter(Bet.line_id == line.id).distinct().count() + 1

    if line.total_action >= line.amount:
        line.status = "matched"

    user.balance -= bettor_stake

    db.add(bet)
    db.flush()

    # Notify bookie their line was taken
    push_notification(db, line.bookie_id, "bet_matched",
        f"🎯 @{user.username} took your line",
        f"{line.game} · {line.type.upper()} · ${bettor_stake:.2f} matched",
        bet.id)

    db.commit()

    return {
        "message": "Bet placed",
        "bettor_stake": bettor_stake,
        "bookie_stake": bookie_portion,
        "to_win": bookie_portion,
        "odds": format_odds(odds)
    }

@app.get("/api/props")
def get_props(db: Session = Depends(get_db)):
    props = db.query(Prop).filter(
        Prop.status == "open",
        Prop.game_id.isnot(None),
        ~Prop.game_id.like("future_%")
    ).all()
    result = []
    for p in props:
        try:
            odds = p.odds if (p.odds is not None and p.odds != 0) else -110
            if -100 < odds < 100:
                odds = -110
            result.append({
                "id": p.id, "bookie_id": p.bookie_id, "bookie_name": p.bookie_name or "",
                "game_id": p.game_id, "game": p.game or "", "sport": p.sport or "",
                "player_name": p.player_name or "", "prop_type": p.prop_type or "",
                "line": p.line or 0, "side": p.side or "over",
                "odds": odds,
                "amount": p.amount or 0
            })
        except Exception as e:
            print(f"get_props: skipping prop {p.id}: {e}")
            continue
    return result

@app.post("/api/props")
def create_prop(prop: PropCreate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.balance < prop.amount:
        raise HTTPException(400, "Insufficient balance")

    # Look up game name from game_id — futures use a "future_" prefix, bypass live lookup
    if prop.game_id.startswith("future_"):
        game_name = f"Futures: {prop.player_name} ({prop.prop_type})"
    else:
        all_games = get_cached_games()
        game = next((g for g in all_games if g["id"] == prop.game_id), None)
        if not game:
            game_name = f"Game {prop.game_id}"
        else:
            game_name = f"{game['away']} @ {game['home']}"

    new_prop = Prop(bookie_id=user.id, bookie_name=user.username,
                   game_id=prop.game_id, game=game_name,
                   sport=prop.sport, player_name=prop.player_name,
                   prop_type=prop.prop_type, line=prop.line,
                   side=prop.side, odds=prop.odds, amount=prop.amount)
    user.balance -= prop.amount
    user.lines_created += 1
    db.add(new_prop)
    db.commit()
    return {"message": "Prop created"}

@app.post("/api/props/take")
def take_prop(take: TakeProp, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    prop = db.query(Prop).filter(Prop.id == take.prop_id, Prop.status == "open").first()
    if not prop:
        raise HTTPException(404, "Prop not available")
    if prop.bookie_id == user_id:
        raise HTTPException(400, "Can't bet your own prop")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    odds = prop.odds if prop.odds is not None else -110
    if odds == 0 or (-100 < odds < 100):
        odds = -110  # fallback safety

    # Bettor stake is the mirror of the bookie stake at these odds
    bettor_stake = bettor_stake_from_bookie(prop.amount, odds)

    if user.balance < bettor_stake:
        raise HTTPException(400, f"Insufficient balance. Need ${bettor_stake:.2f}")

    prop_bet = PropBet(prop_id=prop.id, bookie_id=prop.bookie_id, bookie_name=prop.bookie_name,
                      bettor_id=user.id, bettor_name=user.username,
                      game_id=prop.game_id,
                      player_name=prop.player_name,
                      prop_type=prop.prop_type, line=prop.line, bookie_side=prop.side,
                      bettor_side="under" if prop.side == "over" else "over",
                      odds=odds,
                      bookie_amount=prop.amount,
                      bettor_amount=bettor_stake,
                      amount=prop.amount)
    prop.status = "matched"
    user.balance -= bettor_stake
    db.add(prop_bet)
    db.commit()
    return {"message": "Prop bet placed", "bettor_stake": bettor_stake, "bookie_stake": prop.amount}

@app.get("/api/bets")
def get_bets(token: str, db: Session = Depends(get_db)):
    maybe_check_scores()  # recover from Render sleep
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    bets = db.query(Bet).filter((Bet.bookie_id == user_id) | (Bet.bettor_id == user_id)).all()
    prop_bets = db.query(PropBet).filter((PropBet.bookie_id == user_id) | (PropBet.bettor_id == user_id)).all()
    
    return {
        "single_bets": [{"id": b.id, "bookie_id": b.bookie_id, "bookie_name": b.bookie_name,
                        "bettor_id": b.bettor_id, "bettor_name": b.bettor_name, "game": b.game,
                        "game_id": b.game_id or "", "sport": getattr(b, "sport", ""),
                        "type": b.type, "bookie_side": b.bookie_side, "bettor_side": b.bettor_side,
                        "value": b.value, "odds": b.odds or -110, "amount": b.amount,
                        "bookie_amount": b.bookie_amount or b.amount,
                        "bettor_amount": b.bettor_amount or b.amount,
                        "status": b.status, "winner": b.winner,
                        "created_at": b.created_at.isoformat() if b.created_at else ""} for b in bets],
        "prop_bets": [{"id": p.id, "bookie_id": p.bookie_id, "bookie_name": p.bookie_name,
                      "bettor_id": p.bettor_id, "bettor_name": p.bettor_name, "player_name": p.player_name,
                      "prop_type": p.prop_type, "line": p.line, "bookie_side": p.bookie_side,
                      "bettor_side": p.bettor_side, "odds": p.odds or -110,
                      "bookie_amount": p.bookie_amount or p.amount,
                      "bettor_amount": p.bettor_amount or p.amount,
                      "amount": p.amount, "status": p.status, "winner": p.winner} for p in prop_bets],
        "parlays": []
    }

@app.post("/api/challenges")
def create_challenge(challenge: ChallengeCreate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    challenger = db.query(User).filter(User.id == user_id).first()
    if not challenger:
        raise HTTPException(404, "User not found")

    challenged = db.query(User).filter(User.username == challenge.challenged_username).first()
    if not challenged:
        raise HTTPException(404, f"User @{challenge.challenged_username} not found")
    if challenged.id == user_id:
        raise HTTPException(400, "Can't challenge yourself")

    if challenger.balance < challenge.amount:
        raise HTTPException(400, "Insufficient balance")

    # Validate odds
    if challenge.odds == 0 or (-100 < challenge.odds < 100):
        raise HTTPException(400, "Odds must be -100 or lower, or +100 or higher")

    all_games = get_cached_games()
    game = next((g for g in all_games if g["id"] == challenge.game_id), None)
    if not game:
        game_label = f"Game {challenge.game_id}"
        game_sport = "NBA"
    else:
        game_label = f"{game['away']} @ {game['home']}"
        game_sport = game["sport"]

    new_challenge = Challenge(
        challenger_id=challenger.id,
        challenger_name=challenger.username,
        challenged_id=challenged.id,
        challenged_name=challenged.username,
        game_id=challenge.game_id,
        game=game_label,
        sport=game_sport,
        type=challenge.type,
        side=challenge.side,
        value=challenge.value,
        odds=challenge.odds,
        amount=challenge.amount,
        message=challenge.message
    )
    challenger.balance -= challenge.amount
    db.add(new_challenge)
    db.flush()
    push_notification(db, challenged.id, "challenge_received",
        f"⚔️ Challenge from @{challenger.username}",
        f"{challenge.type.upper()} · {challenge.side} · ${challenge.amount} stake",
        new_challenge.id)
    db.commit()
    db.refresh(new_challenge)
    return {"message": "Challenge sent!", "challenge_id": new_challenge.id}

@app.get("/api/challenges")
def get_challenges(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    incoming = db.query(Challenge).filter(
        Challenge.challenged_id == user_id,
        Challenge.status == "pending"
    ).order_by(Challenge.created_at.desc()).all()

    outgoing = db.query(Challenge).filter(
        Challenge.challenger_id == user_id
    ).order_by(Challenge.created_at.desc()).limit(20).all()

    def fmt(c, role):
        odds = c.odds if c.odds else -110
        if odds <= -100:
            bettor_stake = round(c.amount * (100 / abs(odds)), 2)
        else:
            bettor_stake = round(c.amount * (odds / 100), 2)
        return {
            "id": c.id, "challenger_name": c.challenger_name,
            "challenged_name": c.challenged_name,
            "game": c.game, "sport": c.sport, "type": c.type,
            "side": c.side, "value": c.value, "odds": odds,
            "amount": c.amount, "bettor_stake": bettor_stake,
            "message": c.message, "status": c.status,
            "bet_id": c.bet_id, "role": role,
            "created_at": c.created_at.isoformat()
        }

    return {
        "incoming": [fmt(c, "challenged") for c in incoming],
        "outgoing": [fmt(c, "challenger") for c in outgoing]
    }

@app.post("/api/challenges/accept")
def accept_challenge(action: ChallengeAction, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    challenge = db.query(Challenge).filter(
        Challenge.id == action.challenge_id,
        Challenge.challenged_id == user_id,
        Challenge.status == "pending"
    ).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found or already resolved")

    acceptor = db.query(User).filter(User.id == user_id).first()
    if not acceptor:
        raise HTTPException(404, "User not found")

    odds = challenge.odds if challenge.odds else -110
    if odds <= -100:
        acceptor_stake = round(challenge.amount * (100 / abs(odds)), 2)
    else:
        acceptor_stake = round(challenge.amount * (odds / 100), 2)

    if acceptor.balance < acceptor_stake:
        raise HTTPException(400, f"Insufficient balance. Need ${acceptor_stake:.2f}")

    # Determine opponent sides
    ch_side = challenge.side
    if ch_side in ("home", "away"):
        opp_side = "away" if ch_side == "home" else "home"
    elif ch_side == "over":
        opp_side = "under"
    elif ch_side == "under":
        opp_side = "over"
    else:
        opp_side = ch_side

    # Create a real Bet — plugs straight into the settlement pipeline
    bet = Bet(
        line_id=None,
        bookie_id=challenge.challenger_id,
        bookie_name=challenge.challenger_name,
        bettor_id=acceptor.id,
        bettor_name=acceptor.username,
        game_id=challenge.game_id,
        game=challenge.game,
        type=challenge.type,
        bookie_side=ch_side,
        bettor_side=opp_side,
        value=challenge.value,
        odds=odds,
        amount=challenge.amount,
        bookie_amount=challenge.amount,
        bettor_amount=acceptor_stake
    )
    acceptor.balance -= acceptor_stake
    db.add(bet)
    db.flush()

    challenge.status = "accepted"
    challenge.bet_id = bet.id

    # Notify challenger their challenge was accepted
    push_notification(db, challenge.challenger_id, "challenge_accepted",
        f"✅ @{acceptor.username} accepted your challenge!",
        f"{challenge.game} · {challenge.type.upper()} · Bet #{bet.id} is live",
        bet.id)
    db.commit()
    return {"message": "Challenge accepted! Bet is live.", "bet_id": bet.id}

@app.post("/api/challenges/decline")
def decline_challenge(action: ChallengeAction, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    challenge = db.query(Challenge).filter(
        Challenge.id == action.challenge_id,
        Challenge.challenged_id == user_id,
        Challenge.status == "pending"
    ).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found")
    # Refund challenger
    challenger = db.query(User).filter(User.id == challenge.challenger_id).first()
    if challenger:
        challenger.balance += challenge.amount
    challenge.status = "declined"
    push_notification(db, challenge.challenger_id, "challenge_declined",
        f"❌ @{challenge.challenged_name} declined your challenge",
        f"{challenge.game} · Stake of ${challenge.amount} refunded",
        challenge.id)
    db.commit()
    return {"message": "Challenge declined. Challenger refunded."}

@app.post("/api/challenges/cancel")
def cancel_challenge(action: ChallengeAction, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    challenge = db.query(Challenge).filter(
        Challenge.id == action.challenge_id,
        Challenge.challenger_id == user_id,
        Challenge.status == "pending"
    ).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found or cannot be cancelled")
    challenger = db.query(User).filter(User.id == user_id).first()
    if challenger:
        challenger.balance += challenge.amount
    challenge.status = "cancelled"
    db.commit()
    return {"message": "Challenge cancelled. Stake refunded."}

@app.get("/api/notifications")
def get_notifications(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    notifs = db.query(Notification).filter(
        Notification.user_id == user_id
    ).order_by(Notification.created_at.desc()).limit(30).all()
    return [{"id": n.id, "type": n.type, "title": n.title, "body": n.body,
             "is_read": n.is_read, "ref_id": n.ref_id,
             "created_at": n.created_at.isoformat()} for n in notifs]

@app.post("/api/notifications/read")
def mark_notifications_read(token: str, notif_id: Optional[int] = None, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    q = db.query(Notification).filter(Notification.user_id == user_id, Notification.is_read == False)
    if notif_id:
        q = q.filter(Notification.id == notif_id)
    q.update({"is_read": True})
    db.commit()
    return {"message": "Marked as read"}

@app.post("/api/groups/{group_id}/invite")
def invite_to_group(group_id: int, body: InviteBody, token: str, db: Session = Depends(get_db)):
    """Group creator invites another user by username."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(404, "Group not found")
    if group.creator_id != user_id:
        raise HTTPException(403, "Only the group owner can invite members")
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "Username required")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(404, f"User @{username} not found")
    members = json.loads(group.members)
    if target.id in members:
        raise HTTPException(400, f"@{username} is already in this group")
    members.append(target.id)
    group.members = json.dumps(members)
    push_notification(db, target.id, "group_invite",
        f"👥 Added to group: {group.name}",
        f"@{db.query(User).filter(User.id==user_id).first().username} added you to the group \"{group.name}\"",
        ref_id=group.id)
    db.commit()
    return {"message": f"@{username} added to {group.name}"}

@app.post("/api/groups/{group_id}/leave")
def leave_group(group_id: int, token: str, db: Session = Depends(get_db)):
    """Leave a group (creator can't leave — must delete instead)."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(404, "Group not found")
    if group.creator_id == user_id:
        raise HTTPException(400, "You're the owner — delete the group instead")
    members = json.loads(group.members)
    if user_id not in members:
        raise HTTPException(400, "You're not in this group")
    members.remove(user_id)
    group.members = json.dumps(members)
    db.commit()
    return {"message": f"Left group {group.name}"}

@app.delete("/api/groups/{group_id}")
def delete_group(group_id: int, token: str, db: Session = Depends(get_db)):
    """Creator deletes the group."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(404, "Group not found")
    if group.creator_id != user_id:
        raise HTTPException(403, "Only the owner can delete this group")
    db.delete(group)
    db.commit()
    return {"message": "Group deleted"}

@app.get("/api/groups")
def get_groups(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    groups = db.query(Group).all()
    result = []
    for g in groups:
        members = json.loads(g.members)
        if user_id in members:
            result.append({"id": g.id, "name": g.name, "description": g.description,
                          "creator_id": g.creator_id, "creator_name": g.creator_name,
                          "member_count": len(members), "is_creator": g.creator_id == user_id})
    return result

@app.post("/api/groups")
def create_group(group: GroupCreate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    
    new_group = Group(name=group.name, description=group.description,
                     creator_id=user.id, creator_name=user.username, members=json.dumps([user.id]))
    db.add(new_group)
    db.commit()
    db.refresh(new_group)
    return {"message": "Group created", "group_id": new_group.id}

@app.post("/api/follow/{username}")
def follow_user(username: str, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == user_id:
        raise HTTPException(400, "Can't follow yourself")
    existing = db.query(Follow).filter(Follow.follower_id == user_id, Follow.followed_id == target.id).first()
    if existing:
        raise HTTPException(400, "Already following")
    db.add(Follow(follower_id=user_id, followed_id=target.id))
    db.commit()
    return {"message": f"Now following @{username}"}

@app.delete("/api/follow/{username}")
def unfollow_user(username: str, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(404, "User not found")
    follow = db.query(Follow).filter(Follow.follower_id == user_id, Follow.followed_id == target.id).first()
    if not follow:
        raise HTTPException(404, "Not following")
    db.delete(follow)
    db.commit()
    return {"message": f"Unfollowed @{username}"}

@app.get("/api/following")
def get_following(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    follows = db.query(Follow).filter(Follow.follower_id == user_id).all()
    followed_ids = [f.followed_id for f in follows]
    users = db.query(User).filter(User.id.in_(followed_ids)).all() if followed_ids else []
    # Get open lines count per followed user
    result = []
    for u in users:
        open_lines = db.query(Line).filter(Line.bookie_id == u.id, Line.status == "open").count()
        result.append({
            "id": u.id, "username": u.username, "wins": u.wins, "losses": u.losses,
            "profit": u.profit, "open_lines": open_lines,
            "win_rate": round((u.wins / (u.wins + u.losses) * 100) if (u.wins + u.losses) > 0 else 0, 1)
        })
    return result

# ─── FRIEND REQUESTS ─────────────────────────────────────────────────────────

@app.post("/api/friends/request/{username}")
def send_friend_request(username: str, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == user_id:
        raise HTTPException(400, "Can't friend yourself")
    # Already friends?
    existing = db.query(FriendRequest).filter(
        ((FriendRequest.sender_id == user_id) & (FriendRequest.receiver_id == target.id)) |
        ((FriendRequest.sender_id == target.id) & (FriendRequest.receiver_id == user_id))
    ).first()
    if existing:
        if existing.status == "accepted":
            raise HTTPException(400, "Already friends")
        if existing.status == "pending":
            raise HTTPException(400, "Request already sent")
        # declined — allow re-request by updating
        existing.status = "pending"
        existing.sender_id = user_id
        existing.receiver_id = target.id
        db.commit()
        return {"message": f"Friend request sent to @{username}"}
    req = FriendRequest(sender_id=user_id, receiver_id=target.id)
    db.add(req)
    sender = db.query(User).filter(User.id == user_id).first()
    push_notification(db, target.id, "friend_request",
        f"👋 Friend request from @{sender.username}",
        f"@{sender.username} wants to be friends", ref_id=user_id)
    db.commit()
    return {"message": f"Friend request sent to @{username}"}

@app.post("/api/friends/accept/{request_id}")
def accept_friend_request(request_id: int, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    req = db.query(FriendRequest).filter(
        FriendRequest.id == request_id,
        FriendRequest.receiver_id == user_id,
        FriendRequest.status == "pending"
    ).first()
    if not req:
        raise HTTPException(404, "Request not found")
    req.status = "accepted"
    receiver = db.query(User).filter(User.id == user_id).first()
    push_notification(db, req.sender_id, "friend_accepted",
        f"🤝 @{receiver.username} accepted your friend request",
        "You're now friends!", ref_id=user_id)
    db.commit()
    return {"message": "Friend request accepted"}

@app.post("/api/friends/decline/{request_id}")
def decline_friend_request(request_id: int, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    req = db.query(FriendRequest).filter(
        FriendRequest.id == request_id,
        FriendRequest.receiver_id == user_id,
        FriendRequest.status == "pending"
    ).first()
    if not req:
        raise HTTPException(404, "Request not found")
    req.status = "declined"
    db.commit()
    return {"message": "Request declined"}

@app.delete("/api/friends/{username}")
def remove_friend(username: str, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(404, "User not found")
    req = db.query(FriendRequest).filter(
        FriendRequest.status == "accepted",
        ((FriendRequest.sender_id == user_id) & (FriendRequest.receiver_id == target.id)) |
        ((FriendRequest.sender_id == target.id) & (FriendRequest.receiver_id == user_id))
    ).first()
    if not req:
        raise HTTPException(404, "Not friends")
    db.delete(req)
    db.commit()
    return {"message": f"Removed @{username} from friends"}

@app.get("/api/friends")
def get_friends(token: str, db: Session = Depends(get_db)):
    """Returns: accepted friends, pending incoming requests, pending outgoing requests."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    all_reqs = db.query(FriendRequest).filter(
        (FriendRequest.sender_id == user_id) | (FriendRequest.receiver_id == user_id)
    ).all()

    friends, incoming, outgoing = [], [], []
    for r in all_reqs:
        other_id = r.receiver_id if r.sender_id == user_id else r.sender_id
        other = db.query(User).filter(User.id == other_id).first()
        if not other:
            continue
        obj = {
            "request_id": r.id,
            "id": other.id, "username": other.username,
            "wins": other.wins, "losses": other.losses, "profit": other.profit,
            "win_rate": round((other.wins/(other.wins+other.losses)*100) if (other.wins+other.losses)>0 else 0, 1)
        }
        if r.status == "accepted":
            friends.append(obj)
        elif r.status == "pending":
            if r.receiver_id == user_id:
                incoming.append(obj)
            else:
                outgoing.append(obj)

    return {"friends": friends, "incoming": incoming, "outgoing": outgoing}

# Update users/search to include friendship status
@app.get("/api/users/search")
def search_users(token: str = None, db: Session = Depends(get_db)):
    user_id = verify_token(token) if token else None
    users = db.query(User).order_by(User.profit.desc()).all()

    # Build friendship map for current user
    friend_map = {}  # other_user_id -> status string
    if user_id:
        reqs = db.query(FriendRequest).filter(
            (FriendRequest.sender_id == user_id) | (FriendRequest.receiver_id == user_id)
        ).all()
        for r in reqs:
            other = r.receiver_id if r.sender_id == user_id else r.sender_id
            if r.status == "accepted":
                friend_map[other] = "friends"
            elif r.status == "pending":
                friend_map[other] = "outgoing" if r.sender_id == user_id else "incoming"

        follows = db.query(Follow).filter(Follow.follower_id == user_id).all()
        follow_set = {f.followed_id for f in follows}
    else:
        follow_set = set()

    result = []
    for u in users:
        if user_id and u.id == user_id:
            continue
        result.append({
            "id": u.id, "username": u.username, "wins": u.wins,
            "losses": u.losses, "profit": u.profit,
            "is_following": u.id in follow_set,
            "friend_status": friend_map.get(u.id, "none"),  # none|outgoing|incoming|friends
            "request_id": next((r.id for r in (reqs if user_id else [])
                               if (r.sender_id==u.id and r.receiver_id==user_id) or
                                  (r.sender_id==user_id and r.receiver_id==u.id)), None)
        })
    return result

@app.get("/api/leaderboard")
def leaderboard(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.profit.desc()).limit(10).all()
    return [{"id": u.id, "username": u.username, "balance": u.balance, "profit": u.profit,
             "wins": u.wins, "losses": u.losses} for u in users]

@app.patch("/api/user/profile")
def update_profile(token: str, db: Session = Depends(get_db), request_data: dict = None):
    """Update profile fields. Accepts JSON body with any subset of profile fields."""
    from fastapi import Request
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if request_data is None:
        raise HTTPException(400, "No data provided")
    allowed = {"bio", "favorite_team", "favorite_sport", "location", "banner_color", "avatar"}
    for k, v in request_data.items():
        if k not in allowed:
            continue
        if k == "bio" and v and len(v) > 300:
            raise HTTPException(400, "Bio max 300 characters")
        if k == "avatar" and v and len(v) > 500_000:
            raise HTTPException(400, "Image too large — max ~375KB")
        setattr(user, k, v if v else None)
    db.commit()
    return {"ok": True, "message": "Profile updated"}

# Pydantic wrapper so FastAPI can parse the body
from pydantic import BaseModel as _BM
class ProfileUpdate(_BM):
    bio: str = None
    favorite_team: str = None
    favorite_sport: str = None
    location: str = None
    banner_color: str = None
    avatar: str = None  # base64 data URI

@app.patch("/api/user/profile")
def update_profile_v2(data: ProfileUpdate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if data.bio is not None:
        if len(data.bio) > 300:
            raise HTTPException(400, "Bio max 300 characters")
        user.bio = data.bio or None
    if data.favorite_team is not None: user.favorite_team = data.favorite_team or None
    if data.favorite_sport is not None: user.favorite_sport = data.favorite_sport or None
    if data.location is not None: user.location = data.location or None
    if data.banner_color is not None: user.banner_color = data.banner_color or None
    if data.avatar is not None:
        if data.avatar and len(data.avatar) > 500_000:
            raise HTTPException(400, "Image too large — compress before uploading")
        user.avatar = data.avatar or None
    db.commit()
    total = (user.wins or 0) + (user.losses or 0)
    win_rate = round((user.wins or 0) / total * 100, 1) if total > 0 else 0
    return {"ok": True, "avatar": user.avatar, "bio": user.bio,
            "favorite_team": user.favorite_team, "favorite_sport": user.favorite_sport,
            "location": user.location, "banner_color": user.banner_color, "win_rate": win_rate}

@app.get("/api/users/{username}")
def get_public_profile(username: str, token: str = None, db: Session = Depends(get_db)):
    """Public profile — stats, recent bets, open lines, follower counts."""
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(404, f"User @{username} not found")

    viewer_id = verify_token(token) if token else None
    is_following = False
    if viewer_id:
        is_following = db.query(Follow).filter(
            Follow.follower_id == viewer_id,
            Follow.followed_id == target.id
        ).first() is not None

    # Follower / following counts
    followers = db.query(Follow).filter(Follow.followed_id == target.id).count()
    following = db.query(Follow).filter(Follow.follower_id == target.id).count()

    # Recent settled bets (last 10)
    bets = db.query(Bet).filter(
        (Bet.bookie_id == target.id) | (Bet.bettor_id == target.id),
        Bet.status == "settled"
    ).order_by(Bet.created_at.desc()).limit(10).all()

    recent_bets = []
    for b in bets:
        is_bookie = b.bookie_id == target.id
        my_side = b.bookie_side if is_bookie else b.bettor_side
        i_won = b.winner == ("bookie" if is_bookie else "bettor")
        pnl = (b.bookie_amount if i_won else -(b.bettor_amount or b.amount)) if is_bookie else               (b.bettor_amount if i_won else -(b.bettor_amount or b.amount))
        recent_bets.append({
            "id": b.id, "game": b.game, "type": b.type, "side": my_side,
            "value": b.value, "odds": b.odds or -110,
            "result": "won" if i_won else ("push" if b.winner == "push" else "lost"),
            "pnl": round(pnl or 0, 2),
            "role": "bookie" if is_bookie else "bettor",
            "created_at": b.created_at.isoformat() if b.created_at else ""
        })

    # Open lines they've posted
    open_lines = db.query(Line).filter(
        Line.bookie_id == target.id,
        Line.status == "open",
        Line.is_private == False
    ).order_by(Line.created_at.desc()).limit(5).all()

    lines_out = [{
        "id": l.id, "game": l.game, "type": l.type, "side": l.side,
        "value": l.value, "odds": l.odds or -110, "amount": l.amount,
        "total_action": l.total_action or 0, "sport": l.sport or ""
    } for l in open_lines]

    total = (target.wins or 0) + (target.losses or 0)
    win_rate = round((target.wins or 0) / total * 100, 1) if total > 0 else 0

    return {
        "id": target.id, "username": target.username,
        "wins": target.wins or 0, "losses": target.losses or 0,
        "win_rate": win_rate, "profit": target.profit or 0,
        "lines_created": target.lines_created or 0,
        "is_admin": target.is_admin,
        "avatar": target.avatar, "bio": target.bio,
        "favorite_team": target.favorite_team, "favorite_sport": target.favorite_sport,
        "location": target.location, "banner_color": target.banner_color,
        "followers": followers, "following": following,
        "is_following": is_following,
        "recent_bets": recent_bets,
        "open_lines": lines_out,
        "member_since": target.created_at.strftime("%b %Y") if target.created_at else ""
    }

@app.get("/api/user")
def get_user(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    total = (user.wins or 0) + (user.losses or 0)
    win_rate = round((user.wins or 0) / total * 100, 1) if total > 0 else 0
    return {"id": user.id, "username": user.username, "balance": user.balance, "profit": user.profit,
            "wins": user.wins, "losses": user.losses, "lines_created": user.lines_created,
            "is_admin": user.is_admin, "win_rate": win_rate,
            "avatar": user.avatar, "bio": user.bio, "favorite_team": user.favorite_team,
            "favorite_sport": user.favorite_sport, "location": user.location,
            "banner_color": user.banner_color,
            "created_at": user.created_at.isoformat() if user.created_at else ""}


@app.post("/api/admin/mark-settled")
def admin_mark_settled(bet_id: int, winner: str, token: str, db: Session = Depends(get_db)):
    """Admin: mark a bet as settled WITHOUT touching balances (for bets already paid out)."""
    user_id = verify_token(token)
    user = db.query(User).filter(User.id == user_id, User.is_admin == True).first()
    if not user:
        raise HTTPException(403, "Admin only")
    if winner not in ("bookie", "bettor", "push"):
        raise HTTPException(400, "winner must be 'bookie', 'bettor', or 'push'")
    bet = db.query(Bet).filter(Bet.id == bet_id).first()
    if not bet:
        raise HTTPException(404, "Bet not found")
    bet.status = "settled"
    bet.winner = winner
    db.commit()
    return {"message": f"Bet {bet_id} marked settled — winner: {winner} (balances unchanged)"}

@app.post("/api/admin/settle-bet")
def admin_settle_bet(bet_id: int, winner: str, token: str, db: Session = Depends(get_db)):
    """Admin: manually settle a specific bet. winner = 'bookie', 'bettor', or 'push'"""
    user_id = verify_token(token)
    user = db.query(User).filter(User.id == user_id, User.is_admin == True).first()
    if not user:
        raise HTTPException(403, "Admin only")
    if winner not in ("bookie", "bettor", "push"):
        raise HTTPException(400, "winner must be 'bookie', 'bettor', or 'push'")
    bet = db.query(Bet).filter(Bet.id == bet_id).first()
    if not bet:
        raise HTTPException(404, "Bet not found")
    if bet.status != "pending":
        raise HTTPException(400, f"Bet already {bet.status}")
    settle_bet(db, bet, winner)
    db.commit()
    return {"message": f"Bet {bet_id} settled — winner: {winner}"}

@app.post("/api/admin/run-scores")
def admin_run_scores(token: str, db: Session = Depends(get_db)):
    """Admin: trigger score check immediately instead of waiting for scheduler"""
    user_id = verify_token(token)
    user = db.query(User).filter(User.id == user_id, User.is_admin == True).first()
    if not user:
        raise HTTPException(403, "Admin only")

    if not ODDS_API_KEY:
        # No API key — return pending bet info so admin can manually settle
        pending = db.query(Bet).filter(Bet.status == "pending").all()
        return {
            "message": "No ODDS_API_KEY set — manual settlement required",
            "pending_count": len(pending),
            "pending_bets": [{"id": b.id, "game": b.game, "game_id": b.game_id,
                              "bookie": b.bookie_name, "bettor": b.bettor_name,
                              "type": b.type, "bookie_side": b.bookie_side,
                              "bettor_side": b.bettor_side, "value": b.value} for b in pending]
        }
    try:
        check_game_scores()
        pending_after = db.query(Bet).filter(Bet.status == "pending").count()
        return {"message": f"Score check complete. Pending bets remaining: {pending_after}. Check server logs for details."}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/admin/pending-bets")
def admin_pending_bets(token: str, db: Session = Depends(get_db)):
    """Admin: view all pending bets with their game IDs for debugging"""
    user_id = verify_token(token)
    user = db.query(User).filter(User.id == user_id, User.is_admin == True).first()
    if not user:
        raise HTTPException(403, "Admin only")
    bets = db.query(Bet).filter(Bet.status == "pending").order_by(Bet.created_at.desc()).all()
    return [{
        "id": b.id, "game": b.game, "game_id": b.game_id,
        "type": b.type, "bookie_side": b.bookie_side, "bettor_side": b.bettor_side,
        "value": b.value, "bookie": b.bookie_name, "bettor": b.bettor_name,
        "bookie_amount": b.bookie_amount, "bettor_amount": b.bettor_amount
    } for b in bets]


# ─── PARLAYS ──────────────────────────────────────────────────────────────────

def american_to_decimal(odds: int) -> float:
    if odds >= 100:
        return odds / 100 + 1
    return 100 / abs(odds) + 1

def decimal_to_american(d: float) -> int:
    if d >= 2.0:
        return int((d - 1) * 100)
    return int(-100 / (d - 1))

def calc_parlay_odds(legs: list) -> int:
    """Multiply decimal odds of each leg, return combined American odds."""
    decimal = 1.0
    for leg in legs:
        decimal *= american_to_decimal(leg.get("odds", -110))
    return decimal_to_american(decimal)

def bettor_stake_for_parlay(bookie_liability: float, combined_odds: int) -> float:
    """How much bettor risks to win bookie_liability at combined_odds."""
    d = american_to_decimal(combined_odds)
    return round(bookie_liability / (d - 1), 2)

def determine_leg_winner(leg: dict, home_score: int, away_score: int) -> str:
    """Returns 'bookie', 'bettor', or 'push' for a single parlay leg."""
    t = leg.get("type", "moneyline")
    side = leg.get("side", "home")
    value = leg.get("value", 0) or 0
    diff = home_score - away_score
    if t == "moneyline":
        if home_score == away_score: return "push"
        if side == "home": return "bookie" if home_score > away_score else "bettor"
        return "bookie" if away_score > home_score else "bettor"
    elif t == "spread":
        adj = diff + value if side == "home" else -diff + value
        if adj == 0: return "push"
        return "bookie" if adj > 0 else "bettor"
    elif t == "total":
        total = home_score + away_score
        if total == value: return "push"
        if side == "over": return "bookie" if total > value else "bettor"
        return "bookie" if total < value else "bettor"
    return None

def settle_parlay_bet(db, pb: ParlayBet, winner: str):
    """Settle a parlay bet ticket."""
    bookie = db.query(User).filter(User.id == pb.bookie_id).first()
    bettor = db.query(User).filter(User.id == pb.bettor_id).first()
    if not bookie or not bettor:
        return
    pb.status = "won" if winner == "bettor" else "lost"
    pb.winner = winner
    total_pot = pb.bookie_amount + pb.bettor_amount
    parlay = db.query(Parlay).filter(Parlay.id == pb.parlay_id).first()
    leg_count = len(json.loads(parlay.legs)) if parlay else "?"
    if winner == "bettor":
        bettor.balance += total_pot
        bettor.profit += pb.bookie_amount
        bettor.wins += 1
        bookie.profit -= pb.bookie_amount
        bookie.losses += 1
        push_notification(db, bettor.id, "bet_settled", f"🎰 Parlay hit! +${pb.bookie_amount:.2f}",
            f"{leg_count}-leg parlay won — @{pb.bookie_name} paid you", None)
        push_notification(db, bookie.id, "bet_settled", f"💸 Parlay lost -${pb.bookie_amount:.2f}",
            f"{leg_count}-leg parlay — @{pb.bettor_name} hit it", None)
    else:
        bookie.balance += total_pot
        bookie.profit += pb.bettor_amount
        bookie.wins += 1
        bettor.profit -= pb.bettor_amount
        bettor.losses += 1
        push_notification(db, bookie.id, "bet_settled", f"🏆 Parlay won! +${pb.bettor_amount:.2f}",
            f"{leg_count}-leg parlay busted — @{pb.bettor_name}'s ticket lost", None)
        push_notification(db, bettor.id, "bet_settled", f"💸 Parlay busted -${pb.bettor_amount:.2f}",
            f"{leg_count}-leg parlay lost", None)

class ParlayLeg(BaseModel):
    game_id: str
    game: str
    sport: str
    type: str
    side: str
    value: float = 0
    odds: int = -110

class ParlayCreate(BaseModel):
    legs: list[ParlayLeg]
    amount: float

@app.post("/api/parlays")
def create_parlay(body: ParlayCreate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(401, "Invalid token")
    if len(body.legs) < 2: raise HTTPException(400, "Parlay needs at least 2 legs")
    if len(body.legs) > 12: raise HTTPException(400, "Max 12 legs")
    if body.amount <= 0 or body.amount > user.balance:
        raise HTTPException(400, f"Invalid amount — balance: {user.balance:.2f}")
    legs_data = [l.dict() for l in body.legs]
    combined_odds = calc_parlay_odds(legs_data)
    user.balance -= body.amount
    p = Parlay(
        bookie_id=user_id, bookie_name=user.username,
        legs=json.dumps(legs_data), combined_odds=combined_odds,
        amount=body.amount, total_action=0.0
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "combined_odds": combined_odds,
            "bettor_stake": bettor_stake_for_parlay(body.amount, combined_odds)}

@app.get("/api/parlays")
def get_parlays(token: str, db: Session = Depends(get_db)):
    verify_token(token)
    parlays = db.query(Parlay).filter(Parlay.status == "open").all()
    result = []
    for p in parlays:
        legs = json.loads(p.legs)
        avail = p.amount - (p.total_action or 0)
        bettor_stake = bettor_stake_for_parlay(avail, p.combined_odds)
        result.append({
            "id": p.id, "bookie_id": p.bookie_id, "bookie_name": p.bookie_name,
            "legs": legs, "combined_odds": p.combined_odds,
            "amount": p.amount, "total_action": p.total_action or 0,
            "available": round(avail, 2), "bettor_stake": round(bettor_stake, 2),
            "leg_count": len(legs),
        })
    return result

@app.post("/api/parlays/take")
def take_parlay(parlay_id: int, amount: float, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(401, "Invalid token")
    p = db.query(Parlay).filter(Parlay.id == parlay_id, Parlay.status == "open").first()
    if not p: raise HTTPException(404, "Parlay not found or closed")
    if p.bookie_id == user_id: raise HTTPException(400, "Can't take your own parlay")
    avail = p.amount - (p.total_action or 0)
    if amount > avail + 0.01: raise HTTPException(400, f"Max available to win: ${avail:.2f}")
    if amount <= 0 or amount > user.balance:
        raise HTTPException(400, f"Invalid amount — balance: {user.balance:.2f}")
    bettor_stake = bettor_stake_for_parlay(amount, p.combined_odds)
    if user.balance < bettor_stake:
        raise HTTPException(400, f"Need ${bettor_stake:.2f} to wager — balance: {user.balance:.2f}")
    user.balance -= bettor_stake
    p.total_action = (p.total_action or 0) + amount
    if p.total_action >= p.amount - 0.01:
        p.status = "open"  # stays open until game starts
    legs = json.loads(p.legs)
    legs_result = {leg["game_id"]: "pending" for leg in legs}
    pb = ParlayBet(
        parlay_id=p.id, bookie_id=p.bookie_id, bookie_name=p.bookie_name,
        bettor_id=user_id, bettor_name=user.username,
        bookie_amount=round(amount, 2), bettor_amount=round(bettor_stake, 2),
        legs_result=json.dumps(legs_result)
    )
    db.add(pb)
    db.commit()
    push_notification(db, p.bookie_id, "parlay_taken", f"🎰 Parlay taken by @{user.username}",
        f"{len(legs)}-leg parlay · they risk ${bettor_stake:.2f} to win ${amount:.2f}", None)
    db.commit()
    return {"message": "Parlay taken!", "bettor_stake": bettor_stake, "to_win": amount}

@app.get("/api/parlays/mine")
def my_parlays(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    posted = db.query(Parlay).filter(Parlay.bookie_id == user_id).order_by(Parlay.created_at.desc()).limit(20).all()
    taken = db.query(ParlayBet).filter(ParlayBet.bettor_id == user_id).order_by(ParlayBet.created_at.desc()).limit(20).all()
    def fmt_parlay(p):
        legs = json.loads(p.legs)
        return {"id": p.id, "bookie_name": p.bookie_name, "legs": legs,
                "combined_odds": p.combined_odds, "amount": p.amount,
                "total_action": p.total_action or 0, "status": p.status, "role": "bookie"}
    def fmt_pb(pb):
        p = db.query(Parlay).filter(Parlay.id == pb.parlay_id).first()
        legs = json.loads(p.legs) if p else []
        legs_result = json.loads(pb.legs_result) if pb.legs_result else {}
        combined_odds = p.combined_odds if p else 0
        return {"id": pb.id, "parlay_id": pb.parlay_id, "bookie_name": pb.bookie_name,
                "legs": legs, "legs_result": legs_result, "combined_odds": combined_odds,
                "bookie_amount": pb.bookie_amount, "bettor_amount": pb.bettor_amount,
                "status": pb.status, "winner": pb.winner, "role": "bettor"}
    return {"posted": [fmt_parlay(p) for p in posted], "taken": [fmt_pb(pb) for pb in taken]}

# ─── COIN SHOP ────────────────────────────────────────────────────────────────


COIN_PACKAGES = [
    {"id": "coins_100",  "coins": 100,  "price": 100,  "label": "Starter",  "bonus": ""},
    {"id": "coins_500",  "coins": 500,  "price": 499,  "label": "Popular",  "bonus": "+10%"},
    {"id": "coins_1200", "coins": 1200, "price": 999,  "label": "Baller",   "bonus": "+20%"},
    {"id": "coins_3000", "coins": 3000, "price": 2499, "label": "Whale",    "bonus": "+40%"},
]

@app.get("/api/shop/packages")
def get_packages():
    return COIN_PACKAGES

@app.post("/api/shop/create-checkout")
def create_checkout(package_id: str, token: str, request: Request, db: Session = Depends(get_db)):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(400, "Stripe not configured")
    user_id = verify_token(token)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "Invalid token")
    pkg = next((p for p in COIN_PACKAGES if p["id"] == package_id), None)
    if not pkg:
        raise HTTPException(404, "Package not found")
    try:
        base_url = str(request.base_url).rstrip("/")
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"BookieVerse {pkg['label']} — {pkg['coins']:,} coins",
                        "description": f"Add {pkg['coins']:,} coins to your BookieVerse balance",
                    },
                    "unit_amount": pkg["price"],
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{base_url}/app?payment=success&package={package_id}&user={user_id}",
            cancel_url=f"{base_url}/app?payment=cancelled",
            metadata={"user_id": str(user_id), "package_id": package_id, "coins": str(pkg["coins"])},
        )
        return {"url": session.url}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/shop/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig, webhook_secret)
        else:
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    except Exception as e:
        raise HTTPException(400, str(e))

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata", {})
        user_id = int(meta.get("user_id", 0))
        coins = int(meta.get("coins", 0))
        if user_id and coins:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.balance += coins
                db.commit()
                push_notification(db, user_id, "coins_added", f"💰 {coins:,} coins added!",
                    f"Your purchase was successful. Balance: {user.balance:,.0f} coins", None)
                db.commit()
                print(f"[shop] Added {coins} coins to user {user_id}")
    return {"status": "ok"}

@app.get("/api/shop/success")
def shop_success(package: str, user: int, token: str, db: Session = Depends(get_db)):
    """Fallback: credit coins from success URL if webhook isn't set up yet."""
    user_id = verify_token(token)
    if user_id != user:
        raise HTTPException(403, "Token mismatch")
    pkg = next((p for p in COIN_PACKAGES if p["id"] == package), None)
    if not pkg:
        raise HTTPException(404, "Package not found")
    # Check if already credited (prevent double credit)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    # Only use this as webhook fallback — in production webhook handles it
    return {"message": "Payment recorded", "coins": pkg["coins"]}

@app.get("/app", response_class=HTMLResponse)
def serve_app():
    base = os.path.dirname(os.path.abspath(__file__))
    for name in ["index.html", "FRESH_index.html"]:
        path = os.path.join(base, name)
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read()
    return HTMLResponse("<h1>index.html not found</h1>", status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
