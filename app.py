import requests
import requests, time, json, os, datetime
from flask import Flask, jsonify, render_template_string
import threading

# ================= CONFIG ================= #
BOT_TOKEN = "8765273832:AAEfscmKmUVWOrP0_jsK-0dfIC66ao2e1yg"
CHAT_ID = "7400140409"
SYMBOL = "XAU/USD"
TIMEFRAME = "1h"

STATE_FILE = "state.json"

app = Flask(__name__)

# ================= STATE ================= #
def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {
        "equity": 10000,
        "wins": 0,
        "losses": 0,
        "active_trade": None,
        "equity_curve": [],
        "weights": {"trend": 1.0, "rsi": 1.0, "macd": 1.0, "bos": 1.0},
        "signals_today": 0,
        "last_day": str(datetime.date.today())
    }

state = load_state()

def save():
    json.dump(state, open(STATE_FILE, "w"))

# ================= TELEGRAM ================= #
def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except:
        pass

# ================= DATA (Twelvedata safe cache) ================= #
cache = None
last_fetch = 0

def get_data():
    global cache, last_fetch

    now = time.time()

    if now - last_fetch < 600 and cache:
        return cache

    url = f"https://api.twelvedata.com/time_series?symbol={SYMBOL}&interval=1h&outputsize=100&apikey=6ee724777f5a43ec8859988f2e99cb12"

    r = requests.get(url).json()

    if "values" not in r:
        return cache

    closes = [float(x["close"]) for x in r["values"]][::-1]

    cache = closes
    last_fetch = now

    return closes

# ================= INDICATORS ================= #
def ema(data, n=20):
    k = 2/(n+1)
    e = data[0]
    for x in data:
        e = x*k + e*(1-k)
    return e

def rsi(data):
    gains, losses = [], []
    for i in range(1, len(data)):
        diff = data[i] - data[i-1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    ag = sum(gains[-14:]) / 14
    al = sum(losses[-14:]) / 14 or 1
    return 100 - (100 / (1 + ag / al))

def macd(data):
    return ema(data, 12) - ema(data, 26)

def bos(data):
    if data[-1] > max(data[-10:]):
        return "BULL_BOS"
    if data[-1] < min(data[-10:]):
        return "BEAR_BOS"
    return None

# ================= SCORE ================= #
def sniper_score(data):
    price = data[-1]
    e20 = ema(data, 20)
    e50 = ema(data, 50)
    r = rsi(data)
    m = macd(data)
    b = bos(data)

    score = 0

    if e20 > e50:
        score += 3
    else:
        score -= 3

    score += 2 if m > 0 else -2

    if r < 30:
        score += 3
    elif r > 70:
        score -= 3
    else:
        return 0

    if b == "BULL_BOS":
        score += 2
    elif b == "BEAR_BOS":
        score -= 2

    return score

def grade(score):
    if score >= 8: return "A+"
    if score >= 6: return "A"
    if score >= 4: return "B"
    return None

def signal(score):
    if score >= 4: return "BUY"
    if score <= -4: return "SELL"
    return None

# ================= TP OPTIMIZER ================= #
def tp_levels():
    win_rate = state["wins"] / (state["wins"] + state["losses"] + 1)

    if win_rate > 0.6:
        return 0.020, 0.030, 0.040
    elif win_rate > 0.45:
        return 0.015, 0.020, 0.030
    else:
        return 0.010, 0.015, 0.020

# ================= TRADE SYSTEM ================= #
def open_trade(sig, price, grade):
    tp1, tp2, tp3 = tp_levels()

    state["active_trade"] = {
        "signal": sig,
        "entry": price,
        "tp1": price * (1 + tp1 if sig == "BUY" else 1 - tp1),
        "tp2": price * (1 + tp2 if sig == "BUY" else 1 - tp2),
        "tp3": price * (1 + tp3 if sig == "BUY" else 1 - tp3),
        "sl": price * (0.995 if sig == "BUY" else 1.005),
        "tp1_hit": False,
        "tp2_hit": False
    }

    send(f"""
🚀 NEW TRADE OPENED

📊 GOLD
🚦 {sig}
🏆 Grade: {grade}

💰 Entry: {price}
🎯 TP1 / TP2 / TP3 ACTIVE
🛑 SL ACTIVE
""")

# ================= LIVE TRADE MONITOR ================= #
def monitor(price):
    t = state["active_trade"]
    if not t:
        return

    if t["signal"] == "BUY":

        if price >= t["tp1"]:
            t["tp1_hit"] = True
            t["sl"] = t["entry"]

        if price >= t["tp2"]:
            t["tp2_hit"] = True

        if price >= t["tp3"]:
            send("🏁 TP3 HIT WIN")
            state["active_trade"] = None
            state["wins"] += 1
            return

        if price <= t["sl"]:
            send("❌ SL HIT LOSS")
            state["active_trade"] = None
            state["losses"] += 1
            return

    else:

        if price <= t["tp1"]:
            t["tp1_hit"] = True
            t["sl"] = t["entry"]

        if price <= t["tp2"]:
            t["tp2_hit"] = True

        if price <= t["tp3"]:
            send("🏁 TP3 HIT WIN")
            state["active_trade"] = None
            state["wins"] += 1
            return

        if price >= t["sl"]:
            send("❌ SL HIT LOSS")
            state["active_trade"] = None
            state["losses"] += 1
            return

# ================= MAIN LOOP ================= #
def calculate_signal(data):
    rsi = data["rsi"]
    ema20 = data["ema20"]
    ema50 = data["ema50"]
    macd = data["macd"]
    price = data["price"]

    score = 0

    # EMA trend
    if ema20 > ema50:
        score += 1
    else:
        score -= 1

    # RSI logic
    if rsi < 30:
        score += 2
    elif rsi > 70:
        score -= 2

    # MACD momentum
    if macd > 0:
        score += 1
    else:
        score -= 1

    # decision
    if score >= 3:
        return "BUY 📈", "Strong", "A+", score
    elif score == 2:
        return "BUY 📈", "Medium", "A", score
    elif score <= -3:
        return "SELL 📉", "Strong", "A+", score
    elif score == -2:
        return "SELL 📉", "Medium", "A", score
    else:
        return "HOLD ⏸", "Weak", "B", score
def run_bot():
    
    def get_live_data(symbol="XAU/USD"):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1h&outputsize=50&apikey={API_KEY}"

    response = requests.get(url).json()

    if "values" not in response:
        return None

    closes = [float(i["close"]) for i in response["values"]]

    price = closes[0]

    # Simple indicator calculations (basic version)
    ema20 = sum(closes[:20]) / 20
    ema50 = sum(closes[:50]) / 50 if len(closes) >= 50 else ema20

    # RSI simple approximation
    gains = [closes[i] - closes[i+1] for i in range(14)]
    avg_gain = sum([g for g in gains if g > 0]) / 14 if gains else 0
    avg_loss = abs(sum([g for g in gains if g < 0]) / 14) if gains else 1

    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    rsi = 100 - (100 / (1 + rs))

    macd = ema20 - ema50

    data = get_live_data("XAU/USD")

if not data:
    continue
    while True:

        data = {
            "price": 21878,
            "rsi": 72,
            "ema20": 22000,
            "ema50": 21500,
            "macd": 1.5
        }

        signal, strength, grade, score = calculate_signal(data)

        # 🚫 skip weak signals
        if grade == "B":
            continue

        message = f"""
🤖 SNIPER FOREX BOT
📅 Gold | BTC/USD | EUR/USD
────────────────────────────

💰 Price: {data['price']}
📊 RSI: {data['rsi']}
📈 EMA20: {data['ema20']}
📉 EMA50: {data['ema50']}
⚡ MACD: {data['macd']}
🎯 Score: {score}

🚦 Signal: {signal}
💪 Strength: {strength}
🏷 Grade: {grade}
"""

        send(message)
# ================= DASHBOARD ================= #
@app.route("/")
def home():
    return render_template_string("""
    <h1>SNIPER AI DASHBOARD</h1>
    <h3>Equity: {{equity}}</h3>
    <h3>Wins: {{wins}} | Losses: {{losses}}</h3>
    <h3>Active Trade: {{trade}}</h3>
    """,
    equity=state["equity"],
    wins=state["wins"],
    losses=state["losses"],
    trade=bool(state["active_trade"])
    )

@app.route("/data")
def data():
    return jsonify(state)

# ================= START ================= #

if __name__ == "__main__":
    import threading

    def start_bot():
        run_bot()

    threading.Thread(target=start_bot, daemon=True).start()

    app.run(host="0.0.0.0", port=10000)
