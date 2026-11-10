# ATR 5.0 Auto Scanner - Telegram Version
# Buy: Weekly Close > BB Upper (55, 3.7) AND RSI > 50, Max 25, 4%
# Sell: 1) -20% first 5 days 2) Daily Close < Weekly 34 MA 3) Daily Close < HH - ATR*5.0
import yfinance as yf
import pandas as pd
import numpy as np
import urllib.request, io, os, json, requests
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MY_HOLDINGS = json.loads(os.getenv("MY_HOLDINGS", "{}"))
MY_CAPITAL = float(os.getenv("MY_CAPITAL", "100000"))

def send_telegram(msg):
    if not TELEGRAM_TOKEN:
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Telegram max 4096 chars, split if needed
    for i in range(0, len(msg), 4000):
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg[i:i+4000], "parse_mode": "Markdown"}, timeout=20)

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def atr_calc(df, period=14):
    tr1 = df['High'] - df['Low']
    tr2 = (df['High'] - df['Close'].shift()).abs()
    tr3 = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

today = datetime.now()
weekday = today.weekday()
is_buy_day = weekday in [4, 5, 6]  # Fri, Sat, Sun

try:
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = urllib.request.urlopen(req, timeout=20).read().decode()
    tickers = [s + ".NS" for s in pd.read_csv(io.StringIO(data))["Symbol"].tolist()]
except:
    tickers = ["RELIANCE.NS","TCS.NS","INFY.NS","EXIDEIND.NS"]

messages = [f"*ATR 5.0 Scan - {today.strftime('%A, %d %b %Y')}*"]

# SELL CHECK
sell_msgs = []
hold_count = 0
for ticker, val in MY_HOLDINGS.items():
    try:
        entry_date_str, entry_price = val[0], float(val[1])
        entry_date = pd.to_datetime(entry_date_str)
        dfd = yf.download(ticker, start="2023-01-01", interval="1d", progress=False, auto_adjust=True)
        if isinstance(dfd.columns, pd.MultiIndex):
            dfd.columns = dfd.columns.get_level_values(0)
        dfd.index = pd.to_datetime(dfd.index)
        dfd = dfd[~dfd.index.duplicated(keep='last')].sort_index()
        dfw = dfd['Close'].resample('W-FRI').last().to_frame(name='Close')
        dfw['High'] = dfd['High'].resample('W-FRI').max()
        dfw['Low'] = dfd['Low'].resample('W-FRI').min()
        dfw['MA34'] = dfw['Close'].rolling(34).mean()
        dfw['ATR'] = atr_calc(dfw, 14)
        last_close = float(dfd.iloc[-1]['Close'])
        last_ma34 = float(dfw.iloc[-1]['MA34'])
        last_atr = float(dfw.iloc[-1]['ATR'])
        since_entry = dfd[dfd.index >= entry_date]
        hh = float(since_entry['High'].max()) if len(since_entry) > 0 else last_close
        chandelier = hh - 5.0 * last_atr
        days_held = len(dfd[dfd.index >= entry_date])
        ret_pct = (last_close / entry_price - 1) * 100
        reason = None
        if days_held <= 5 and last_close < entry_price * 0.80:
            reason = "-20% First Week"
        elif last_close < last_ma34:
            reason = "Below Weekly 34 MA"
        elif last_close < chandelier:
            reason = "Below ATR 5.0"
        if reason:
            sell_msgs.append(f"SELL {ticker.replace('.NS','')} @ {last_close:.2f} | {ret_pct:.1f}% | {reason} | Sell NEXT OPEN")
        else:
            hold_count += 1
    except Exception as e:
        print(f"Failed {ticker}: {e}")

if len(MY_HOLDINGS) == 0:
    messages.append("\n*SELL:* No holdings")
elif sell_msgs:
    messages.append("\n*SELL - ACTION NEEDED:*")
    for s in sell_msgs:
        messages.append(f"🔴 {s}")
else:
    messages.append(f"\n*SELL:* ✅ No SELL - All {hold_count} HOLD")

# BUY CHECK
if is_buy_day:
    buy_list = []
    for ticker in tickers:
        try:
            dfd = yf.download(ticker, start="2023-01-01", interval="1d", progress=False, auto_adjust=True)
            if dfd is None or len(dfd) < 200: continue
            if isinstance(dfd.columns, pd.MultiIndex):
                dfd.columns = dfd.columns.get_level_values(0)
            dfd.index = pd.to_datetime(dfd.index)
            dfd = dfd[~dfd.index.duplicated(keep='last')].sort_index()
            dfw = dfd['Close'].resample('W-FRI').last().to_frame(name='Close')
            dfw['MA55'] = dfw['Close'].rolling(55).mean()
            dfw['STD55'] = dfw['Close'].rolling(55).std()
            dfw['BB_Upper'] = dfw['MA55'] + 3.7 * dfw['STD55']
            dfw['RSI'] = rsi(dfw['Close'], 14)
            last = dfw.iloc[-1]
            prev = dfw.iloc[-2]
            if (last['Close'] > last['BB_Upper']) and (last['RSI'] > 50):
                buy_list.append({'Symbol': ticker.replace('.NS',''), 'Close': round(float(last['Close']),2), 'RSI': round(float(last['RSI']),1)})
        except: continue
    buy_list = sorted(buy_list, key=lambda x: x['RSI'], reverse=True)
    free_slots = 25 - len(MY_HOLDINGS)
    if not buy_list:
        messages.append("\n*BUY (Monday):* No signals. Hold cash.")
    else:
        messages.append(f"\n*BUY (Monday 3:15 PM) - Top {free_slots} by RSI:*")
        for b in buy_list[:free_slots]:
            qty = int((MY_CAPITAL*0.04) // b['Close'])
            messages.append(f"🟢 {b['Symbol']} @ {b['Close']} | RSI {b['RSI']} | Qty ~{qty}")
        messages.append(f"\nFree slots: {free_slots} | Per trade: Rs {MY_CAPITAL*0.04:,.0f}")
else:
    messages.append("\n*BUY:* Skipped (not Fri/Sat/Sun)")

messages.append("\n_If Monday holiday, buy Tuesday. If sell day holiday, sell next trading day. Ignore Muhurat._")
final_msg = "\n".join(messages)
print(final_msg)
send_telegram(final_msg)
