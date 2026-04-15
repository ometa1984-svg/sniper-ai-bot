from flask import Flask, jsonify
import requests
import threading
import time

app = Flask(__name__)

# ================= GLOBAL STATE ================= #
state = {
    "active_trade": None,
    "last_signal_time": 0
}

ai_memory = {
    "wins": 0,
    "losses": 0,
    "total_trades": 0
}

# ================= TELEGRAM SEND ================= #
def send(message):
    print(message)  # replace with your Telegram send logic

# ================= LIVE DATA ================= #
def get_live_data(symbol="XAU/USD"):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1h&outputsize=50&apikey=6ee724777f5a43ec8859988f2e99cb12"

    response = requests.get(url).json()

    if "values" not in response:
        return None

    closes = [float(i["close"]) for i in response["values"]]

    price = closes[0]

    ema20 = sum(closes[:20]) / 20
    ema50 = sum(closes[:50]) / 50 if len(closes) >= 50 else ema20

    gains = [closes[i] - closes[i+1] for i in range(14)]
    avg_gain = sum([g for g in gains if g > 0]) / 14 if gains else 0
    avg_loss = abs(sum([g for g in gains if g < 0]) / 14) if gains else 1

    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    rsi = 100 - (100 / (1 + rs))

    macd = ema20 - ema50

    return {
        "price": price,
        "rsi": rsi,
        "ema20": ema20,
        "ema50": ema50,
        "macd": macd
    }

# ================= SIGNAL ENGINE ================= #
def calculate_signal(data):
    score = 0

    if data["ema20"] > data["ema50"]:
        score += 1
    else:
        score -= 1

    if data["rsi"] < 30:
        score += 2
    elif data["rsi"] > 70:
        score -= 2

    if data["macd"] > 0:
        score += 1
    else:
        score -= 1

    if ai_memory["wins"] > ai_memory["losses"]:
        score += 1

    if score >= 4:
        return "BUY 📈", "Strong", "A+", score
    elif score == 3:
        return "BUY 📈", "Medium", "A", score
    elif score <= -4:
        return "SELL 📉", "Strong", "A+", score
    elif score == -3:
        return "SELL 📉", "Medium", "A", score
    else:
        return "HOLD ⏸", "Weak", "B", score

# ================= MARKET FILTER ================= #
def market_filter(data):
    volatility = abs(data["ema20"] - data["ema50"])
    return volatility >= 5

# ================= TRADE BUILDER ================= #
def build_trade(price, direction):
    if "BUY" in direction:
        return {
            "direction": "BUY",
            "entry": price,
            "tp1": price * 1.002,
            "tp2": price * 1.005,
            "tp3": price * 1.010,
            "sl": price * 0.995,
            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,
            "closed": False
        }
    else:
        return {
            "direction": "SELL",
            "entry": price,
            "tp1": price * 0.998,
            "tp2": price * 0.995,
            "tp3": price * 0.990,
            "sl": price * 1.005,
            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,
            "closed": False
        }

# ================= TRADE TRACKER ================= #
def track_trade(trade, price):
    updates = []

    if trade["direction"] == "BUY":

        if not trade["tp1_hit"] and price >= trade["tp1"]:
            trade["tp1_hit"] = True
            updates.append("🎯 TP1 HIT")

        if not trade["tp2_hit"] and price >= trade["tp2"]:
            trade["tp2_hit"] = True
            updates.append("🎯 TP2 HIT")

        if not trade["tp3_hit"] and price >= trade["tp3"]:
            trade["tp3_hit"] = True
            updates.append("🎯 TP3 HIT")

        if price <= trade["sl"]:
            trade["closed"] = True
            updates.append("🛑 SL HIT")

    else:

        if not trade["tp1_hit"] and price <= trade["tp1"]:
            trade["tp1_hit"] = True
            updates.append("🎯 TP1 HIT")

        if not trade["tp2_hit"] and price <= trade["tp2"]:
            trade["tp2_hit"] = True
            updates.append("🎯 TP2 HIT")

        if not trade["tp3_hit"] and price <= trade["tp3"]:
            trade["tp3_hit"] = True
            updates.append("🎯 TP3 HIT")

        if price >= trade["sl"]:
            trade["closed"] = True
            updates.append("🛑 SL HIT")

    return updates

# ================= AI MEMORY ================= #
def update_ai_memory(result):
    ai_memory["total_trades"] += 1

    if result == "WIN":
        ai_memory["wins"] += 1
    else:
        ai_memory["losses"] += 1

# ================= MAIN BOT ================= #
def run_bot():
    while True:

        data = get_live_data("XAU/USD")

        if not data:
            time.sleep(60)
            continue

        if not market_filter(data):
            time.sleep(60)
            continue

        signal, strength, grade, score = calculate_signal(data)

        trade = state["active_trade"]

        # OPEN TRADE
        if trade is None or trade["closed"]:

            if grade != "B":

                trade = build_trade(data["price"], signal)
                state["active_trade"] = trade

                send(f"""
🚀 NEW TRADE
{signal}
Entry: {trade['entry']}
TP1: {trade['tp1']}
TP2: {trade['tp2']}
TP3: {trade['tp3']}
SL: {trade['sl']}
""")

        # TRACK TRADE
        else:

            updates = track_trade(trade, data["price"])

            for u in updates:
                send(f"""
📊 UPDATE
{u}
Price: {data['price']}
""")

            if trade["closed"]:

                if trade["tp1_hit"] or trade["tp2_hit"] or trade["tp3_hit"]:
                    update_ai_memory("WIN")
                else:
                    update_ai_memory("LOSS")

                send(f"""
📴 TRADE CLOSED
Wins: {ai_memory['wins']}
Losses: {ai_memory['losses']}
""")

                state["active_trade"] = None

        time.sleep(60)

# ================= FLASK ================= #
@app.route("/")
def home():
    return "AI SNIPER PRO RUNNING"

@app.route("/data")
def data():
    return jsonify(state)

# ================= START ================= #
if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
