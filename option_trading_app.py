# option_trading_app.py
# COMPLETE UPDATED FILE WITH TELEGRAM POLLING

from flask import Flask, render_template, jsonify, request
import json
import os
from datetime import datetime
import time
import threading
import requests  # ADDED FOR TELEGRAM API
import uuid
import sqlite3
from crypto_optiontrading import DeltaOptionTrader
from deltaprotraderweb import TradingBot, send_telegram_alert
from web_screener import screener_bp
import subprocess  # Add this import at the top of the file

# Load configuration
def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return None

config = load_config()
if config:
    api_key = config.get('api_key')
    api_secret = config.get('api_secret')
else:
    # Fallback to default (for testing only)
    api_key = "2oGdnPmil61fl4R6t8mPx"
    api_secret = "zEnD12f4O73Wc1eoziNVQQ3BcUgSyBL"

print(f"API Key Loaded: {api_key[:4]}...")
print(f"API Secret Loaded: {api_secret[:4]}...")

os.environ['DELTA_API_KEY'] = api_key
os.environ['DELTA_API_SECRET'] = api_secret

app = Flask(__name__)
app.register_blueprint(screener_bp, url_prefix='/screener')

# ============ TELEGRAM CONFIGURATION ============
TELEGRAM_BOT_TOKEN = '7956030237:AAHNzQejy0_q69NrVVGDr5erKmc5kbd2Apg'
DEFAULT_CHAT_ID = '8008414806'

# ============ SQLITE DATABASE SETUP ============
def init_db():
    """Initialize SQLite database"""
    try:
        conn = sqlite3.connect('trading_config.db')
        cursor = conn.cursor()
        
        # Table for index exit levels
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS index_exit_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                above_price REAL,
                above_type TEXT,
                below_price REAL,
                below_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table for pending trigger orders
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_trigger_orders (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                side TEXT NOT NULL,
                size INTEGER NOT NULL,
                trigger_price REAL NOT NULL,
                trigger_condition TEXT NOT NULL,
                mark_price REAL,
                total_cost REAL,
                time_limit INTEGER,
                expires_at REAL,
                created_at TEXT,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Error initializing database: {e}")

def save_index_exit_levels(above_price, above_type, below_price, below_type):
    """Save index exit levels to database"""
    try:
        conn = sqlite3.connect('trading_config.db')
        cursor = conn.cursor()
        
        # Clear old entries
        cursor.execute('DELETE FROM index_exit_levels')
        
        # Insert new entry
        cursor.execute('''
            INSERT INTO index_exit_levels (above_price, above_type, below_price, below_type)
            VALUES (?, ?, ?, ?)
        ''', (above_price, above_type, below_price, below_type))
        
        conn.commit()
        conn.close()
        print(f"💾 Saved index exit levels to DB: above={above_price}({above_type}), below={below_price}({below_type})")
        return True
    except Exception as e:
        print(f"❌ Error saving to DB: {e}")
        return False

def load_index_exit_levels():
    """Load index exit levels from database"""
    try:
        conn = sqlite3.connect('trading_config.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT above_price, above_type, below_price, below_type FROM index_exit_levels ORDER BY id DESC LIMIT 1')
        row = cursor.fetchone()
        conn.close()
        
        if row:
            levels = {
                'above': {'price': row[0], 'type': row[1]},
                'below': {'price': row[2], 'type': row[3]}
            }
            print(f"📂 Loaded saved levels from DB: {levels}")
            return levels
        else:
            print("ℹ️ No saved levels found in DB")
            return None
    except Exception as e:
        print(f"❌ Error loading from DB: {e}")
        return None

def save_pending_order_to_db(order_data):
    """Save pending trigger order to database"""
    try:
        conn = sqlite3.connect('trading_config.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO pending_trigger_orders 
            (id, symbol, product_id, side, size, trigger_price, trigger_condition, mark_price, total_cost, time_limit, expires_at, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            order_data['id'],
            order_data['symbol'],
            order_data['product_id'],
            order_data['side'],
            order_data['size'],
            order_data['trigger_price'],
            order_data['trigger_condition'],
            order_data.get('mark_price', 0),
            order_data.get('total_cost', 0),
            order_data.get('time_limit'),
            order_data.get('expires_at'),
            order_data.get('created_at'),
            order_data.get('status', 'pending')
        ))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving pending order to DB: {e}")
        return False

def load_pending_orders_from_db():
    """Load all pending trigger orders from database"""
    try:
        conn = sqlite3.connect('trading_config.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM pending_trigger_orders WHERE status = 'pending'")
        rows = cursor.fetchall()
        
        orders = []
        for row in rows:
            order = {
                'id': row[0],
                'symbol': row[1],
                'product_id': row[2],
                'side': row[3],
                'size': row[4],
                'trigger_price': row[5],
                'trigger_condition': row[6],
                'mark_price': row[7],
                'total_cost': row[8],
                'time_limit': row[9],
                'expires_at': row[10],
                'created_at': row[11],
                'status': row[12]
            }
            orders.append(order)
        
        conn.close()
        print(f"📂 Loaded {len(orders)} pending orders from DB")
        return orders
    except Exception as e:
        print(f"Error loading pending orders from DB: {e}")
        return []

def update_order_status_in_db(order_id, status, order_id_executed=None):
    """Update order status in database"""
    try:
        conn = sqlite3.connect('trading_config.db')
        cursor = conn.cursor()
        
        if status == 'executed':
            cursor.execute('''
                UPDATE pending_trigger_orders 
                SET status = ?, executed_at = ?, order_id = ?
                WHERE id = ?
            ''', (status, datetime.utcnow().isoformat(), order_id_executed, order_id))
        else:
            cursor.execute('''
                UPDATE pending_trigger_orders 
                SET status = ?
                WHERE id = ?
            ''', (status, order_id))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating order status in DB: {e}")
        return False

def delete_order_from_db(order_id):
    """Delete order from database"""
    try:
        conn = sqlite3.connect('trading_config.db')
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM pending_trigger_orders WHERE id = ?', (order_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting order from DB: {e}")
        return False

# Initialize database
init_db()

# Initialize components
trading_bot = TradingBot()
option_trader = DeltaOptionTrader(api_key=api_key, api_secret=api_secret)

# Load saved index exit levels from database
saved_levels = load_index_exit_levels()

# Store trading bot instance
app.trading_bot = trading_bot

if saved_levels:
    app.trading_bot.index_exit_params = saved_levels
    print(f"✅ Loaded saved index exit levels: {saved_levels}")
else:
    app.trading_bot.index_exit_params = {
        'above': {'price': None, 'type': None},
        'below': {'price': None, 'type': None}
    }
    print("ℹ️ No saved levels found, using defaults")

# Load pending trigger orders from database
app.pending_trigger_orders = load_pending_orders_from_db()

# Trade history storage
TRADE_HISTORY_FILE = "trade_history.json"

# Helper function for expiry dates
def generate_expiry_dates():
    from datetime import datetime, timedelta
    utc_now = datetime.utcnow()
    ist_now = utc_now + timedelta(hours=5, minutes=30)
    cutoff = time(17, 0)
    
    if ist_now.time() < cutoff:
        primary_date = ist_now.date()
    else:
        primary_date = ist_now.date() + timedelta(days=1)
    
    dates = [primary_date + timedelta(days=i) for i in range(3)]
    formatted_dates = [d.strftime("%m/%d/%y") for d in dates]
    formatted_dates.append("Custom Date")
    print(f"Generated Expiry Dates: {formatted_dates}")
    return formatted_dates

# ============ TELEGRAM POLLING FUNCTIONS ============

def send_telegram_response(chat_id, text):
    """Send message to specific chat ID"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            return True
        else:
            print(f"❌ Telegram send failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Telegram send error: {e}")
        return False

def telegram_polling():
    """Poll Telegram for new messages and respond to commands"""
    print("🤖 Starting Telegram polling for /btc, /pnl, /soa commands...")
    last_update_id = 0
    
    # Dictionary to track confirmation states
    confirmation_states = {}
    
    while True:
        try:
            # Get updates from Telegram
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {
                'offset': last_update_id + 1,
                'timeout': 10,
                'allowed_updates': ['message']
            }
            
            response = requests.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('ok') and data.get('result'):
                    for update in data['result']:
                        last_update_id = update['update_id']
                        
                        if 'message' in update and 'text' in update['message']:
                            chat_id = update['message']['chat']['id']
                            text = update['message']['text'].strip()
                            
                            print(f"📨 Received Telegram message: {text} from chat_id: {chat_id}")
                            
                            # ============ CHECK FOR CONFIRMATION RESPONSES FIRST ============
                            if chat_id in confirmation_states:
                                pending_command = confirmation_states[chat_id].get('command')
                                
                                if text.lower() in ['y', 'yes']:
                                    # Execute the pending command
                                    if pending_command == 'soa':
                                        # Square off all positions
                                        pnl_before = trading_bot.get_pnl_info()
                                        result = trading_bot.exit_all_positions()
                                        
                                        # Prepare response message
                                        response_text = (
                                            f"✅ <b>ALL POSITIONS SQUARED OFF</b>\n\n"
                                            f"<b>Status:</b> Success\n"
                                            f"<b>Time:</b> {datetime.now().strftime('%H:%M:%S')}\n\n"
                                        )
                                        
                                        if pnl_before.get('success') and pnl_before.get('position_count', 0) > 0:
                                            response_text += f"<b>Positions Closed:</b> {pnl_before['position_count']}\n"
                                            if pnl_before.get('total_pnl'):
                                                pnl_sign = '+' if pnl_before['total_pnl'] >= 0 else ''
                                                response_text += f"<b>Final PNL:</b> {pnl_sign}{pnl_before['total_pnl']:.2f} USD\n"
                                        
                                        send_telegram_response(chat_id, response_text)
                                        trading_bot.log_message(f"✅ /soa command executed for chat_id: {chat_id}")
                                    
                                    elif pending_command == 'restart':
                                        # Execute restart
                                        try:
                                            # Send restarting message
                                            send_telegram_response(chat_id, "🔄 <b>Restarting Flask server...</b>\nBot will reconnect in 10-15 seconds.")
                                            
                                            # Log before restart
                                            trading_bot.log_message("Server restart initiated via Telegram /restart command")
                                            
                                            # Create restart batch file content
                                            batch_content = '''@echo off
echo ==========================================
echo          RESTARTING FLASK SERVER
echo ==========================================
echo.
echo Stopping existing Flask server...
taskkill /F /IM python.exe >nul 2>&1
timeout /t 3 /nobreak >nul
echo Starting new Flask server...
cd "C:\\Users\\Akshay\\OneDrive\\Desktop\\BTC_OptionTrader"
start "Flask Trading Bot" python option_trading_app.py
echo.
echo Server restart initiated!
echo Check the new command window for Flask server.
echo ==========================================
timeout /t 5 /nobreak >nul
'''
                                            
                                            # Save batch file
                                            batch_path = r"C:\Users\Akshay\OneDrive\Desktop\BTC_OptionTrader\restart_server.bat"
                                            with open(batch_path, 'w') as f:
                                                f.write(batch_content)
                                            
                                            # Execute batch file
                                            import subprocess
                                            subprocess.Popen([batch_path], shell=True)
                                            
                                            # Also log in our current process
                                            print("=" * 50)
                                            print("🔄 RESTART COMMAND EXECUTED")
                                            print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
                                            print("=" * 50)
                                            
                                            # Wait a bit before the current process gets killed
                                            time.sleep(2)
                                            
                                        except Exception as e:
                                            error_msg = f"❌ Restart failed: {str(e)}"
                                            send_telegram_response(chat_id, error_msg)
                                            print(f"Restart error: {e}")
                                    
                                    # Clear confirmation state
                                    del confirmation_states[chat_id]
                                    continue
                                
                                elif text.lower() in ['n', 'no']:
                                    # Cancel the operation
                                    response_text = f"❌ <b>Operation Cancelled</b>\n{pending_command.upper()} command was cancelled."
                                    send_telegram_response(chat_id, response_text)
                                    del confirmation_states[chat_id]
                                    trading_bot.log_message(f"❌ {pending_command} command cancelled for chat_id: {chat_id}")
                                    continue
                                
                                else:
                                    # Invalid response, ask again
                                    response_text = (
                                        f"⚠️ <b>Invalid Response</b>\n\n"
                                        f"Please reply with either:\n"
                                        f"<b>Y</b> or <b>YES</b> - Confirm\n"
                                        f"<b>N</b> or <b>NO</b> - Cancel\n\n"
                                        f"<i>Current pending command: /{pending_command}</i>"
                                    )
                                    send_telegram_response(chat_id, response_text)
                                    continue
                            
                            # ============ HANDLE REGULAR COMMANDS ============
                            
                            # Handle /soa command
                            if text.lower() == '/soa':
                                print(f"✅ Processing /soa command from chat_id: {chat_id}")
                                
                                # First, get current positions
                                pnl_info = trading_bot.get_pnl_info()
                                
                                if not pnl_info.get('success'):
                                    response_text = f"⚠️ Could not fetch position data: {pnl_info.get('error', 'Unknown error')}"
                                    send_telegram_response(chat_id, response_text)
                                    continue
                                
                                position_count = pnl_info.get('position_count', 0)
                                
                                if position_count == 0:
                                    response_text = "ℹ️ <b>No Active Positions</b>\n\nThere are no open positions to square off."
                                    send_telegram_response(chat_id, response_text)
                                else:
                                    # Store confirmation state
                                    confirmation_states[chat_id] = {'command': 'soa', 'timestamp': time.time()}
                                    
                                    # Create confirmation message
                                    response_text = (
                                        f"⚠️ <b>CONFIRM SQUARE OFF ALL</b>\n\n"
                                        f"<b>Positions Found:</b> {position_count}\n"
                                    )
                                    
                                    # Show position details if available
                                    positions = pnl_info.get('positions', [])
                                    for idx, pos in enumerate(positions[:3]):  # Show first 3
                                        pnl_sign = '+' if pos['unrealized_pnl'] >= 0 else ''
                                        response_text += f"\n<b>{pos['symbol']}</b> ({pos['side']})\n"
                                        response_text += f"Size: {abs(pos['size'])} | PNL: {pnl_sign}{pos['unrealized_pnl']:.2f} USD\n"
                                    
                                    if position_count > 3:
                                        response_text += f"\n... and {position_count - 3} more positions\n"
                                    
                                    total_pnl = pnl_info.get('total_pnl', 0)
                                    total_pnl_sign = '+' if total_pnl >= 0 else ''
                                    response_text += f"\n<b>Total PNL:</b> {total_pnl_sign}{total_pnl:.2f} USD\n\n"
                                    response_text += f"<b>Are you sure you want to square off ALL positions?</b>\n\n"
                                    response_text += f"Reply with:\n"
                                    response_text += f"<b>Y</b> - Yes, square off all positions\n"
                                    response_text += f"<b>N</b> - No, cancel this operation\n\n"
                                    response_text += f"<i>This action will close ALL positions and cancel ALL orders.</i>"
                                    
                                    send_telegram_response(chat_id, response_text)
                                    trading_bot.log_message(f"⚠️ /soa confirmation requested for chat_id: {chat_id}, positions: {position_count}")
                            
                            # Handle /restart command
                            elif text.lower() == '/restart':
                                print(f"✅ Processing /restart command from chat_id: {chat_id}")
                                
                                # Store confirmation state
                                confirmation_states[chat_id] = {'command': 'restart', 'timestamp': time.time()}
                                
                                response_text = (
                                    f"⚠️ <b>SERVER RESTART REQUESTED</b>\n\n"
                                    f"This will:\n"
                                    f"• Stop the Flask server\n"
                                    f"• Wait 3 seconds\n"
                                    f"• Restart it in a new window\n"
                                    f"• Bot will be offline for 10-15 seconds\n\n"
                                    f"<b>Are you sure?</b>\n\n"
                                    f"Reply with:\n"
                                    f"<b>Y</b> or <b>YES</b> - Confirm and restart\n"
                                    f"<b>N</b> or <b>NO</b> - Cancel operation"
                                )
                                
                                send_telegram_response(chat_id, response_text)
                                trading_bot.log_message(f"⚠️ /restart confirmation requested for chat_id: {chat_id}")
                            
                            # Handle /refresh_close command
                            elif text.lower() == '/refresh_close':
                                print(f"✅ Processing /refresh_close command from chat_id: {chat_id}")
                                
                                # First get current data
                                current_price = trading_bot.live_price
                                old_previous_close = trading_bot.previous_day_close
                                
                                # Update previous day close
                                success = trading_bot.update_previous_day_close()
                                
                                if success:
                                    new_previous_close = trading_bot.previous_day_close
                                    
                                    # Calculate new change
                                    if current_price and new_previous_close:
                                        change = current_price - new_previous_close
                                        change_percent = (change / new_previous_close) * 100
                                        
                                        if change >= 0:
                                            change_formatted = f"+${abs(change):.2f}"
                                            percent_formatted = f"(+{abs(change_percent):.2f}%)"
                                            emoji = "🟢"
                                        else:
                                            change_formatted = f"-${abs(change):.2f}"
                                            percent_formatted = f"(-{abs(change_percent):.2f}%)"
                                            emoji = "🔴"
                                    
                                    response_text = (
                                        f"✅ <b>Previous Day Close Refreshed</b>\n\n"
                                        f"<b>Old Reference:</b> ${old_previous_close:,.2f}\n"
                                        f"<b>New Reference:</b> ${new_previous_close:,.2f}\n\n"
                                    )
                                    
                                    if current_price and new_previous_close:
                                        response_text += (
                                            f"<b>Current Price:</b> ${current_price:.2f}\n"
                                            f"<b>New 24h Change:</b> {emoji} {change_formatted}{percent_formatted}\n\n"
                                        )
                                    
                                    response_text += f"<i>Updated at: {datetime.now().strftime('%H:%M:%S')}</i>"
                                    
                                else:
                                    response_text = "❌ <b>Failed to refresh</b>\n\nCould not update previous day close. Check logs."
                                
                                send_telegram_response(chat_id, response_text)
                                trading_bot.log_message(f"✅ Responded to /refresh_close command from chat_id: {chat_id}")
                            
                            # Handle /btc command
                            elif text.lower() == '/btc':
                                print(f"✅ Processing /btc command from chat_id: {chat_id}")
                                
                                # Get BTC data
                                current_price = trading_bot.live_price
                                previous_close = trading_bot.previous_day_close
                                
                                if not current_price or not previous_close or previous_close <= 0:
                                    response_text = "⚠️ BTC price data not available yet. Please try again in a moment."
                                else:
                                    # Calculate 24h change
                                    change = current_price - previous_close
                                    change_percent = (change / previous_close) * 100
                                    
                                    # Format change with emojis
                                    if change >= 0:
                                        # Positive change
                                        change_formatted = f"+${abs(change):.2f}"
                                        percent_formatted = f"(+{abs(change_percent):.2f}%)"
                                        emoji = "🟢"
                                        trend_emoji = "📈"
                                    else:
                                        # Negative change
                                        change_formatted = f"-${abs(change):.2f}"
                                        percent_formatted = f"(-{abs(change_percent):.2f}%)"
                                        emoji = "🔴"
                                        trend_emoji = "📉"
                                    
                                    # Create response message
                                    response_text = (
                                        f"{trend_emoji} <b>BTC Price</b>\n\n"
                                        f"<code>${current_price:.2f}</code>\n\n"
                                        f"<b>24h Change</b>\n"
                                        f"{emoji} <code>{change_formatted}</code>\n"
                                        f"{emoji} <code>{percent_formatted}</code>\n\n"
                                        f"<i>Last updated: {datetime.now().strftime('%H:%M:%S')}</i>"
                                    )
                                
                                # Send response back to Telegram
                                send_telegram_response(chat_id, response_text)
                                trading_bot.log_message(f"✅ Responded to /btc command from chat_id: {chat_id}")
                            
                   
                            # Handle /pnl command
                            # Handle /pnl command
                            elif text.lower() == '/pnl':
                                print(f"✅ Processing /pnl command from chat_id: {chat_id}")
                                
                                # Get accurate PNL information (new improved version)
                                pnl_info = trading_bot.get_pnl_summary()
                                wallet_info = trading_bot.get_accurate_wallet_info()
                                
                                if not pnl_info.get('success'):
                                    response_text = f"⚠️ Could not fetch PNL data: {pnl_info.get('error', 'Unknown error')}"
                                else:
                                    active_positions = pnl_info['active_positions']
                                    total_unrealized_pnl = pnl_info['total_unrealized_pnl']
                                    last_trade_realized_pnl = pnl_info['last_trade_realized_pnl']
                                    
                                    # Start building response - EXACT FORMAT AS REQUESTED
                                    response_text = f"📊 <b>COMPLETE PNL SUMMARY</b>\n\n"
                                    response_text += f"<b>Positions Status:</b> {active_positions} active\n"
                                    
                                    # Add Last Trade Realized PNL
                                    last_trade_sign = '+' if last_trade_realized_pnl >= 0 else ''
                                    response_text += f"<b>Realized PNL (Last Trade):</b> {last_trade_sign}{last_trade_realized_pnl:.2f} USD\n"
                                    
                                    # Add Unrealized PNL only if there are active positions
                                    if active_positions > 0:
                                        unrealized_sign = '+' if total_unrealized_pnl >= 0 else ''
                                        response_text += f"<b>Unrealized PNL:</b> {unrealized_sign}{total_unrealized_pnl:.2f} USD\n"
                                    
                                    # Add wallet information - ONLY USD
                                    if wallet_info.get('success'):
                                        balance = wallet_info['balance']
                                        asset = wallet_info['asset']
                                        
                                        if balance > 0:
                                            # Convert to INR (1 USD = 85 INR)
                                            inr_value = balance * 85
                                            response_text += f"\n<b>💰 WALLET BALANCES</b>\n"
                                            if asset == 'USD':
                                                response_text += f"{asset}: ${balance:.2f} (₹{inr_value:.2f})\n"
                                            elif asset == 'USDT':
                                                response_text += f"{asset}: {balance:.2f} (₹{inr_value:.2f})\n"
                                        else:
                                            response_text += f"\n<b>💰 WALLET BALANCES</b>\n"
                                            response_text += f"USD: $0.00 (₹0.00)\n"
                                    
                                    response_text += f"\n<i>Last updated: {datetime.now().strftime('%H:%M:%S')}</i>"
                                
                                # Send response back to Telegram
                                send_telegram_response(chat_id, response_text)
                                trading_bot.log_message(f"✅ Responded to /pnl command from chat_id: {chat_id}")
                                                        
                            # Handle /start command
                            elif text.lower() == '/start':
                                welcome_text = (
                                    "🤖 <b>BTC Price & PNL Bot</b>\n\n"
                                    "Available commands:\n"
                                    "/btc - Get current BTC price and 24h change\n"
                                    "/pnl - Get your current PNL (Profit and Loss)\n"
                                    "/soa - Square off ALL positions (requires confirmation)\n"
                                    "/refresh_close - Refresh previous day closing price\n"
                                    "/restart - Restart Flask server (requires confirmation)\n"
                                    "/help - Show this help message\n\n"
                                    "Features:\n"
                                    "• Auto daily reset at 05:30 AM IST\n"
                                    "• 30-minute BTC price updates\n"
                                    "• Real-time PNL tracking\n"
                                    "• Position management\n\n"
                                    "<i>Local network only - polling every 10 seconds.</i>"
                                )
                                send_telegram_response(chat_id, welcome_text)
                                trading_bot.log_message(f"✅ Sent welcome message to chat_id: {chat_id}")
                            
                            # Handle /help command
                            elif text.lower() == '/help':
                                help_text = (
                                    "📋 <b>Available Commands</b>\n\n"
                                    "/btc - Get current BTC price and 24h change\n"
                                    "/pnl - Get your current PNL (Profit and Loss)\n"
                                    "/soa - Square off ALL positions (requires confirmation)\n"
                                    "/refresh_close - Refresh previous day closing price\n"
                                    "/restart - Restart Flask server (requires confirmation)\n"
                                    "/start - Start the bot\n"
                                    "/help - Show this help message\n\n"
                                    "Price updates every 30 minutes automatically.\n"
                                    "Manual updates with /btc and /pnl commands anytime."
                                )
                                send_telegram_response(chat_id, help_text)
                                trading_bot.log_message(f"✅ Sent help to chat_id: {chat_id}")
            
            else:
                print(f"❌ Telegram API error: {response.status_code}")
                time.sleep(10)
        
        except requests.exceptions.Timeout:
            # This is expected for long polling - just continue
            continue
            
        except Exception as e:
            print(f"❌ Telegram polling error: {e}")
            time.sleep(10)





# option_trading_app.py में send_periodic_btc_update function को यूँ update करें:

def send_periodic_btc_update():
    """Send BTC price update to Telegram every 30 minutes"""
    while True:
        try:
            # Wait until bot is initialized
            if not trading_bot:
                time.sleep(60)
                continue
            
            # Get current BTC price and previous close
            current_price = trading_bot.live_price
            previous_close = trading_bot.previous_day_close
            
            if current_price and previous_close and previous_close > 0:
                # Calculate 24h change
                change = current_price - previous_close
                change_percent = (change / previous_close) * 100
                
                # Format change with emojis
                if change >= 0:
                    # Positive change
                    change_formatted = f"+${abs(change):.2f}"
                    percent_formatted = f"(+{abs(change_percent):.2f}%)"
                    emoji = "🟢"
                else:
                    # Negative change
                    change_formatted = f"-${abs(change):.2f}"
                    percent_formatted = f"(-{abs(change_percent):.2f}%)"
                    emoji = "🔴"
                
                # Original compact format
                message = f"${current_price:.2f} {emoji} {change_formatted}{percent_formatted} is your 📊 BTC Price Update"
                
                # Send to Telegram
                success = send_telegram_alert(message)
                
                if success:
                    trading_bot.log_message(f"30-minute BTC update sent to Telegram: ${current_price:.2f}")
                else:
                    trading_bot.log_message("Failed to send BTC update to Telegram")
            else:
                trading_bot.log_message("Skipping BTC update - data not available")
            
            # Wait 30 minutes
            time.sleep(1800)  # 1800 seconds = 30 minutes
            
        except Exception as e:
            print(f"Error in periodic BTC update: {e}")
            time.sleep(300)  # Wait 5 minutes on error

# ============ START ALL BACKGROUND THREADS ============

# Start Telegram polling thread
print("🚀 Starting Telegram polling thread...")
telegram_polling_thread = threading.Thread(target=telegram_polling, daemon=True)
telegram_polling_thread.start()
print("✅ Telegram polling thread started successfully")

# Start periodic BTC updates thread
print("🔄 Starting periodic BTC updates thread...")
periodic_update_thread = threading.Thread(target=send_periodic_btc_update, daemon=True)
periodic_update_thread.start()
print("✅ Periodic BTC updates thread started (every 30 minutes)")

# ============ TRADE HISTORY FUNCTIONS ============

def save_trade_to_history(trade_data):
    """Save trade to history JSON file"""
    try:
        trades = []
        
        # Load existing trades if file exists
        if os.path.exists(TRADE_HISTORY_FILE):
            try:
                with open(TRADE_HISTORY_FILE, 'r') as f:
                    trades = json.load(f)
            except:
                trades = []
        
        # Add timestamp if not present
        if 'timestamp' not in trade_data:
            trade_data['timestamp'] = datetime.now().isoformat()
            trade_data['date_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Add ID if not present
        if 'id' not in trade_data:
            trade_data['id'] = str(uuid.uuid4())
        
        # Add trade to beginning of list (newest first)
        trades.insert(0, trade_data)
        
        # Keep only last 100 trades
        if len(trades) > 100:
            trades = trades[:100]
        
        # Save back to file
        with open(TRADE_HISTORY_FILE, 'w') as f:
            json.dump(trades, f, indent=2)
        
        print(f"Trade saved to history: {trade_data['symbol']}")
        return True
    except Exception as e:
        print(f"Error saving trade history: {e}")
        return False

def load_trade_history(count=100):
    """Load trade history from JSON file"""
    try:
        if os.path.exists(TRADE_HISTORY_FILE):
            with open(TRADE_HISTORY_FILE, 'r') as f:
                trades = json.load(f)
            return trades[:count]
        return []
    except Exception as e:
        print(f"Error loading trade history: {e}")
        return []

# ============ FLASK ROUTES ============

@app.route('/')
def index():
    return render_template('option_trading_index.html')

@app.route('/get_state')
def get_state():
    current_price = trading_bot.live_price
    previous_close = trading_bot.previous_day_close
    
    # Calculate change and percentage
    change = 0.0
    change_percent = 0.0
    
    if current_price and previous_close:
        change = current_price - previous_close
        change_percent = (change / previous_close) * 100
    
    return jsonify({
        'live_price': current_price,
        'previous_day_close': previous_close,
        'price_change': change,
        'price_change_percent': change_percent,
        'logs': trading_bot.logs[-10:],
        'current_ip': trading_bot.current_ip,
        'ip_verified': trading_bot.ip_verified,
        'position': trading_bot.position,
        'active_orders': trading_bot.active_orders,
    })

def process_single_option(option_data):
    """Process a single option for display"""
    if 'mark_price' in option_data and isinstance(option_data['mark_price'], str):
        try: 
            option_data['mark_price'] = float(option_data['mark_price'])
        except ValueError: 
            option_data['mark_price'] = None
    
    if 'greeks' in option_data and isinstance(option_data['greeks'], dict):
        for key in ['delta', 'gamma', 'rho', 'theta', 'vega']:
            if key in option_data['greeks'] and isinstance(option_data['greeks'][key], str):
                try: 
                    option_data['greeks'][key] = float(option_data['greeks'][key])
                except ValueError: 
                    option_data['greeks'][key] = None
    
    # Ensure product_id is present (might need to fetch separately)
    if 'product_id' not in option_data or not option_data['product_id']:
        option_data['product_id'] = 0  # Temporary placeholder
    
    return option_data

@app.route('/get_options_chain', methods=['POST'])
def get_options_chain():
    try:
        data = request.get_json()
        expiry_date = data.get('expiry_date')
        option_type_filter = data.get('option_type', 'Calls')
        manual_symbol = data.get('manual_symbol')  # NEW: Add manual symbol parameter

        # NEW: Handle manual symbol lookup
        if manual_symbol:
            # Parse the manual symbol to get expiry
            parts = manual_symbol.split('-')
            if len(parts) != 4:
                return jsonify({'success': False, 'error': 'Invalid symbol format. Use: C/P-BTC-Strike-Expiry'})
            
            expiry_date_str = parts[3]  # Last part is expiry date (ddmmyy)
            
            # Fetch all options for this expiry
            all_options = option_trader.get_options_chain(expiry_date_str)
            if all_options is None:
                return jsonify({'success': False, 'error': 'Failed to fetch options from API.'})
            
            # Find the specific option
            target_option = None
            for opt in all_options:
                if opt.get('symbol') == manual_symbol:
                    target_option = opt
                    break
            
            if not target_option:
                return jsonify({'success': False, 'error': f'Option {manual_symbol} not found'})
            
            # Process the single option
            processed_option = process_single_option(target_option)
            return jsonify({
                'success': True, 
                'options': [processed_option], 
                'filtered_count': 1,
                'expiry_date': expiry_date_str,
                'is_manual': True  # Flag to indicate manual lookup
            })
        
        # Original auto-find logic continues below...
        if not expiry_date:
            return jsonify({'success': False, 'error': 'Expiry date is missing'})

        expiry_date_str = datetime.strptime(expiry_date, "%m/%d/%y").strftime("%d%m%y")
        all_options = option_trader.get_options_chain(expiry_date_str)

        if all_options is None:
            return jsonify({'success': False, 'error': 'Failed to fetch options from API. Check server logs.'})
        if not all_options:
            return jsonify({'success': False, 'error': 'No options found for the selected expiry date.'})

        processed_options = []
        for opt in all_options:
            if 'mark_price' in opt and isinstance(opt['mark_price'], str):
                try: opt['mark_price'] = float(opt['mark_price'])
                except ValueError: opt['mark_price'] = None
            if 'greeks' in opt and isinstance(opt['greeks'], dict):
                for key in ['delta', 'gamma', 'rho', 'theta', 'vega']:
                    if key in opt['greeks'] and isinstance(opt['greeks'][key], str):
                        try: opt['greeks'][key] = float(opt['greeks'][key])
                        except ValueError: opt['greeks'][key] = None
            processed_options.append(opt)
        
        # Rest of the original auto-find logic remains SAME
        if option_type_filter == 'Calls':
            delta_min, delta_max = 0.44, 0.58
            eligible = [o for o in processed_options 
                       if o['contract_type'] == 'call_options' 
                       and o.get('greeks', {}).get('delta') 
                       and delta_min <= abs(o['greeks']['delta']) <= delta_max]
            if eligible: 
                selected_option = max(eligible, key=lambda x: x['greeks']['delta'])
                return jsonify({'success': True, 'options': [selected_option], 'filtered_count': 1, 'expiry_date': expiry_date})
            else:
                return jsonify({'success': False, 'error': f'No suitable Calls option found in delta range for {expiry_date}.'})
        
        elif option_type_filter == 'Puts':
            delta_min, delta_max = 0.44, 0.58
            eligible = [o for o in processed_options 
                       if o['contract_type'] == 'put_options' 
                       and o.get('greeks', {}).get('delta') 
                       and delta_min <= abs(o['greeks']['delta']) <= delta_max]
            if eligible: 
                selected_option = max(eligible, key=lambda x: abs(x['greeks']['delta']))
                return jsonify({'success': True, 'options': [selected_option], 'filtered_count': 1, 'expiry_date': expiry_date})
            else:
                return jsonify({'success': False, 'error': f'No suitable Puts option found in delta range for {expiry_date}.'})

        elif option_type_filter == 'Straddle':
            delta_min, delta_max = 0.44, 0.58
            
            eligible_calls = [o for o in processed_options 
                            if o['contract_type'] == 'call_options' 
                            and o.get('greeks', {}).get('delta') 
                            and delta_min <= abs(o['greeks']['delta']) <= delta_max]
            
            eligible_puts = [o for o in processed_options 
                           if o['contract_type'] == 'put_options' 
                           and o.get('greeks', {}).get('delta') 
                           and delta_min <= abs(o['greeks']['delta']) <= delta_max]
            
            strike_map = {}
            for opt in eligible_calls + eligible_puts:
                strike = float(opt['symbol'].split('-')[2])
                if strike not in strike_map:
                    strike_map[strike] = {'call': None, 'put': None}
                
                if opt['contract_type'] == 'call_options':
                    strike_map[strike]['call'] = opt
                else:
                    strike_map[strike]['put'] = opt
            
            straddles = []
            for strike, pair in strike_map.items():
                if pair['call'] and pair['put']:
                    straddles.append({
                        'strike': strike,
                        'call': pair['call'],
                        'put': pair['put']
                    })
            
            if straddles:
                options = []
                for straddle in straddles:
                    options.append(straddle['call'])
                    options.append(straddle['put'])
                
                return jsonify({'success': True, 'options': options, 'filtered_count': len(straddles), 'expiry_date': expiry_date, 'is_straddle': True})
            else:
                return jsonify({'success': False, 'error': f'No suitable Straddle option found in delta range for {expiry_date}.', 'available_calls': len(eligible_calls) > 0, 'available_puts': len(eligible_puts) > 0})

    except Exception as e:
        print(f"Error in /get_options_chain: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/place_option_order', methods=['POST'])
def place_option_order():
    try:
        data = request.get_json()
        result = option_trader.place_order(
            symbol=data['symbol'], 
            product_id=data['product_id'], 
            side=data['side'], 
            size=data['size']
        )
        
        if 'error' in result:
            return jsonify({'success': False, 'error': result['error']})
        
        # Extract strike price from symbol
        strike_price = None
        if 'symbol' in data and '-' in data['symbol']:
            parts = data['symbol'].split('-')
            if len(parts) >= 3:
                strike_price = parts[2]
        
        # Save trade to history
        trade_data = {
            'symbol': data['symbol'],
            'product_id': data['product_id'],
            'side': data['side'],
            'size': data['size'],
            'price': data.get('mark_price', 0),
            'strike_price': strike_price,
            'total_cost': data.get('total_cost', 0),
            'order_id': result.get('result', {}).get('id', 'N/A'),
            'order_type': data.get('order_type', 'instant'),
            'status': 'executed',
            'is_straddle': data.get('is_straddle', False)
        }
        
        # Save in background thread
        threading.Thread(
            target=lambda: save_trade_to_history(trade_data),
            daemon=True
        ).start()
        
        return jsonify({'success': True, 'order_id': result.get('result', {}).get('id', 'N/A')})
    except Exception as e:
        print(f"Error in /place_option_order: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/fetch_greeks', methods=['POST'])
def fetch_greeks():
    try:
        data = request.get_json()
        option_symbol = data.get('option_symbol')
        
        if not option_symbol:
            return jsonify({'success': False, 'error': 'Option symbol is required'})
        
        parts = option_symbol.split('-')
        if len(parts) != 4:
            return jsonify({'success': False, 'error': 'Invalid option symbol format'})
            
        expiry_date = parts[3]
        
        options_chain = option_trader.get_options_chain(expiry_date)
        if not options_chain:
            return jsonify({'success': False, 'error': 'No options found for this expiry'})
        
        option_details = None
        for opt in options_chain:
            if opt.get('symbol') == option_symbol:
                option_details = opt
                break
                
        if not option_details:
            return jsonify({'success': False, 'error': 'Option not found'})
            
        return jsonify({
            'success': True,
            'mark_price': option_details.get('mark_price'),
            'delta': option_details.get('greeks', {}).get('delta'),
            'gamma': option_details.get('greeks', {}).get('gamma'),
            'theta': option_details.get('greeks', {}).get('theta'),
            'vega': option_details.get('greeks', {}).get('vega'),
            'rho': option_details.get('greeks', {}).get('rho')
        })
        
    except Exception as e:
        print(f"Error in /fetch_greeks: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/calculate_target_price', methods=['POST'])
def calculate_target_price():
    try:
        data = request.get_json()
        current_price = float(data.get('current_price'))
        target_price = float(data.get('target_price'))
        delta = float(data.get('delta'))
        current_option_price = float(data.get('current_option_price'))
        
        price_change = (target_price - current_price) * delta
        estimated_price = current_option_price + price_change
        
        return jsonify({'success': True, 'estimated_price': estimated_price, 'price_change': price_change, 'current_option_price': current_option_price})
        
    except Exception as e:
        print(f"Error in /calculate_target_price: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/update_index_exit', methods=['POST'])
def update_index_exit():
    try:
        data = request.get_json()
        
        # FIRST: Load existing levels from database
        existing_levels = load_index_exit_levels()
        if not existing_levels:
            existing_levels = {
                'above': {'price': None, 'type': None},
                'below': {'price': None, 'type': None}
            }
        
        # Get current values
        current_above_price = existing_levels['above']['price']
        current_above_type = existing_levels['above']['type']
        current_below_price = existing_levels['below']['price']
        current_below_type = existing_levels['below']['type']
        
        # Update ONLY if new value is provided (not None or empty string)
        if 'exit_above' in data:
            if data['exit_above'] not in [None, '', 'null', 'undefined']:
                new_above = float(data['exit_above'])
            else:
                new_above = None
        else:
            # Keep existing value
            new_above = current_above_price
        
        if 'above_type' in data:
            above_type = data['above_type']
            if above_type and above_type not in ['sl', 'target']:
                above_type = None
            new_above_type = above_type
        else:
            # Keep existing type
            new_above_type = current_above_type
        
        # Update below level ONLY if provided
        if 'exit_below' in data:
            if data['exit_below'] not in [None, '', 'null', 'undefined']:
                new_below = float(data['exit_below'])
            else:
                new_below = None
        else:
            # Keep existing value
            new_below = current_below_price
        
        if 'below_type' in data:
            below_type = data['below_type']
            if below_type and below_type not in ['sl', 'target']:
                below_type = None
            new_below_type = below_type
        else:
            # Keep existing type
            new_below_type = current_below_type
        
        # Now set the updated levels
        app.trading_bot.set_index_exit_params(
            above_price=new_above, 
            below_price=new_below, 
            above_type=new_above_type, 
            below_type=new_below_type
        )
        
        # Save to database
        save_index_exit_levels(new_above, new_above_type, new_below, new_below_type)
        
        print(f"✅ UPDATE_EXIT: Levels set and saved to DB: {app.trading_bot.index_exit_params}")
        return jsonify({'success': True, 'levels': app.trading_bot.index_exit_params})
    except Exception as e:
        print(f"❌ Error in update_index_exit: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_index_exit_params', methods=['GET'])
def get_index_exit_params():
    levels = app.trading_bot.index_exit_params
    print(f"📊 GET_EXIT: Returning levels: {levels}")
    return jsonify({'success': True, 'levels': levels})

@app.route('/clear_exit_levels', methods=['POST'])
def clear_exit_levels():
    print(f"🔄 CLEAR_LEVELS: BEFORE clearing: {app.trading_bot.index_exit_params}")
    app.trading_bot.set_index_exit_params(None, None, None, None)
    print(f"🔄 CLEAR_LEVELS: AFTER clearing: {app.trading_bot.index_exit_params}")
    
    # Clear from database
    save_index_exit_levels(None, None, None, None)
    
    return jsonify({'success': True, 'levels': app.trading_bot.index_exit_params})

@app.route('/get_pending_trigger_orders', methods=['GET'])
def get_pending_trigger_orders():
    return jsonify({'success': True, 'orders': app.pending_trigger_orders})

@app.route('/add_trigger_order', methods=['POST'])
def add_trigger_order():
    try:
        data = request.get_json()
        required_fields = ['symbol', 'product_id', 'side', 'size', 'trigger_price', 'trigger_condition']
        
        if not all(field in data for field in required_fields):
            return jsonify({'success': False, 'error': 'Missing required fields'})
            
        trigger_order = {
            **data,
            'id': str(uuid.uuid4()),
            'created_at': datetime.utcnow().isoformat(),
            'status': 'pending',
            'executed_at': None,
            'order_id': None,
            'time_limit': data.get('time_limit')
        }
        
        # If time_limit is provided, calculate expiry time
        if trigger_order['time_limit']:
            import time as t
            trigger_order['expires_at'] = t.time() + (trigger_order['time_limit'] * 60)
        else:
            trigger_order['expires_at'] = None
        
        # Save to database
        save_pending_order_to_db(trigger_order)
        
        # Add to in-memory list
        app.pending_trigger_orders.append(trigger_order)
        
        message = (
            f"⚠️ *New Trigger Order Added*\n\n"
            f"*Symbol:* {data['symbol']}\n"
            f"*Action:* {data['side'].upper()}\n"
            f"*Quantity:* {data['size']}\n"
            f"*Trigger:* {data['trigger_condition']} {data['trigger_price']}\n"
        )
        
        if data.get('time_limit'):
            message += f"*Time Limit:* {data['time_limit']} minutes\n"
        
        message += f"*Status:* Pending"
        trading_bot.send_telegram_notification(message)
        
        return jsonify({'success': True, 'message': 'Trigger order added successfully', 'order_id': trigger_order['id']})
        
    except Exception as e:
        print(f"Error in /add_trigger_order: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/cancel_trigger_order', methods=['POST'])
def cancel_trigger_order():
    try:
        data = request.get_json()
        order_id = data.get('order_id')
        
        for idx, order in enumerate(app.pending_trigger_orders):
            if order.get('id') == order_id:
                cancelled_order = app.pending_trigger_orders.pop(idx)
                
                # Delete from database
                delete_order_from_db(order_id)
                
                message = (
                    f"❌ *Trigger Order Cancelled*\n\n"
                    f"*Symbol:* {cancelled_order['symbol']}\n"
                    f"*Action:* {cancelled_order['side'].upper()}\n"
                    f"*Quantity:* {cancelled_order['size']}\n"
                    f"*Trigger:* {cancelled_order['trigger_condition']} {cancelled_order['trigger_price']}\n"
                )
                trading_bot.send_telegram_notification(message)
                
                return jsonify({'success': True, 'message': 'Order cancelled'})
                
        return jsonify({'success': False, 'error': 'Order not found'})
        
    except Exception as e:
        print(f"Error in /cancel_trigger_order: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/log_exit_event', methods=['POST'])
def log_exit_event():
    """Log exit event when triggered by index-based exit"""
    try:
        data = request.get_json()
        
        # Extract strike price from symbol if available
        strike_price = None
        if data.get('symbol') and '-' in data['symbol']:
            parts = data['symbol'].split('-')
            if len(parts) >= 3:
                strike_price = parts[2]
        
        # Create exit trade entry
        exit_trade = {
            'id': str(uuid.uuid4()),
            'symbol': data.get('symbol', 'Unknown'),
            'product_id': data.get('product_id', ''),
            'side': 'exit',
            'size': 0,  # Size is 0 for exit events
            'price': data.get('price', 0),
            'strike_price': strike_price,
            'total_cost': 0,
            'order_id': 'EXIT-' + str(uuid.uuid4())[:8],
            'order_type': 'index_exit',
            'status': 'executed',
            'exit_type': data.get('exit_type', 'general'),  # 'sl', 'target', 'general'
            'exit_reason': data.get('message', 'Index-based exit'),
            'timestamp': datetime.now().isoformat(),
            'date_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Save to history
        threading.Thread(
            target=lambda: save_trade_to_history(exit_trade),
            daemon=True
        ).start()
        
        # Also log to bot logs
        app.trading_bot.log_message(f"Exit logged: {data.get('message', 'Index exit')}")
        
        return jsonify({'success': True, 'message': 'Exit logged successfully'})
        
    except Exception as e:
        print(f"Error in /log_exit_event: {e}")
        return jsonify({'success': False, 'error': str(e)})

# Trade History Routes
@app.route('/get_recent_trades', methods=['GET'])
def get_recent_trades():
    """Get recent trades for display"""
    try:
        trades = load_trade_history(3)  # Last 3 trades
        return jsonify({'success': True, 'trades': trades})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_all_trades', methods=['GET'])
def get_all_trades():
    """Get all trades for archive view"""
    try:
        trades = load_trade_history(100)
        return jsonify({'success': True, 'trades': trades})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/clear_trade_history', methods=['POST'])
def clear_trade_history():
    """Clear all trade history"""
    try:
        if os.path.exists(TRADE_HISTORY_FILE):
            os.remove(TRADE_HISTORY_FILE)
        return jsonify({'success': True, 'message': 'Trade history cleared'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/send_trade_update', methods=['POST'])
def send_trade_update():
    """Send hourly trade update via Telegram"""
    try:
        data = request.get_json()
        message = data.get('message')
        
        if not message:
            return jsonify({'success': False, 'error': 'No message provided'})
        
        # Send Telegram message
        telegram_msg = f"<b>📊 Trade Update</b>\n\n{message}"
        success = send_telegram_alert(telegram_msg)
        
        return jsonify({'success': success})
        
    except Exception as e:
        print(f"Error in /send_trade_update: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/test_telegram', methods=['GET'])
def test_telegram():
    """Test endpoint to check Telegram connection"""
    try:
        # Test connection to Telegram API
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            bot_info = response.json()
            if bot_info.get('ok'):
                return jsonify({
                    'success': True,
                    'bot_username': bot_info['result']['username'],
                    'bot_name': bot_info['result']['first_name'],
                    'message': '✅ Telegram bot is connected and ready!'
                })
        
        return jsonify({
            'success': False,
            'error': 'Failed to connect to Telegram'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ============ TRIGGER ORDER MONITOR THREAD ============

def trigger_order_monitor():
    """Monitor and execute pending trigger orders with time limits"""
    import time as t
    while True:
        try:
            current_price = trading_bot.live_price
            current_time = t.time()
            
            if current_price and app.pending_trigger_orders:
                for order in app.pending_trigger_orders[:]:
                    if order['status'] == 'pending':
                        # Check if order has expired
                        if order.get('expires_at') and current_time > order['expires_at']:
                            order['status'] = 'expired'
                            order['error'] = 'Time limit expired'
                            
                            # Update database
                            update_order_status_in_db(order['id'], 'expired')
                            
                            message = (
                                f"⏰ *Trigger Order Expired*\n"
                                f"Symbol: {order['symbol']}\n"
                                f"Action: {order['side'].upper()}\n"
                                f"Quantity: {order['size']}\n"
                                f"Trigger: {order['trigger_condition']} {order['trigger_price']}\n"
                                f"Time Limit: {order.get('time_limit', 'N/A')} minutes\n"
                                f"Reason: Time limit exceeded"
                            )
                            trading_bot.send_telegram_notification(message)
                            continue
                        
                        trigger_met = False
                        trigger_price = float(order['trigger_price'])
                        
                        if order['trigger_condition'] == 'above' and current_price >= trigger_price:
                            trigger_met = True
                        elif order['trigger_condition'] == 'below' and current_price <= trigger_price:
                            trigger_met = True
                        
                        if trigger_met:
                            try:
                                result = option_trader.place_order(
                                    symbol=order['symbol'],
                                    product_id=order['product_id'],
                                    side=order['side'],
                                    size=order['size']
                                )
                                
                                if 'error' in result:
                                    order['status'] = 'failed'
                                    order['error'] = result['error']
                                    update_order_status_in_db(order['id'], 'failed')
                                else:
                                    order['status'] = 'executed'
                                    order['executed_at'] = datetime.utcnow().isoformat()
                                    order['order_id'] = result.get('result', {}).get('id', 'N/A')
                                    
                                    # Update database
                                    update_order_status_in_db(order['id'], 'executed', order['order_id'])
                                    
                                    # Extract strike price
                                    strike_price = None
                                    if '-' in order['symbol']:
                                        parts = order['symbol'].split('-')
                                        if len(parts) >= 3:
                                            strike_price = parts[2]
                                    
                                    # Save trade to history
                                    trade_data = {
                                        'symbol': order['symbol'],
                                        'product_id': order['product_id'],
                                        'side': order['side'],
                                        'size': order['size'],
                                        'price': order.get('mark_price', 0),
                                        'strike_price': strike_price,
                                        'total_cost': order.get('total_cost', 0),
                                        'order_id': order['order_id'],
                                        'order_type': 'trigger',
                                        'status': 'executed',
                                        'trigger_price': order['trigger_price'],
                                        'trigger_condition': order['trigger_condition']
                                    }
                                    
                                    threading.Thread(
                                        target=lambda: save_trade_to_history(trade_data),
                                        daemon=True
                                    ).start()
                                    
                                    message = (
                                        f"✅ Trigger Order Executed\n"
                                        f"Symbol: {order['symbol']}\n"
                                        f"Action: {order['side'].upper()}\n"
                                        f"Quantity: {order['size']}\n"
                                        f"Trigger: {order['trigger_condition']} {order['trigger_price']}\n"
                                        f"Executed At: {current_price}"
                                    )
                                    trading_bot.send_telegram_notification(message)
                                
                            except Exception as e:
                                order['status'] = 'failed'
                                order['error'] = str(e)
                                update_order_status_in_db(order['id'], 'failed')
            
            # Clean up executed/failed/expired orders from memory
            app.pending_trigger_orders = [
                o for o in app.pending_trigger_orders 
                if o.get('status') == 'pending'
            ]
            
            t.sleep(5)
        except Exception as e:
            print(f"Trigger monitor error: {e}")
            t.sleep(10)

@app.route('/get_exit_countdown_status', methods=['GET'])
def get_exit_countdown_status():
    """Get current exit countdown status for webpage"""
    try:
        if hasattr(app.trading_bot, 'pending_exit'):
            pending_exit = app.trading_bot.pending_exit
            
            # Calculate remaining time
            remaining = 0
            if pending_exit.get('active') and pending_exit.get('end_time'):
                current_time = time.time()
                remaining = max(0, int(pending_exit['end_time'] - current_time))
            
            return jsonify({
                'success': True,
                'pending_exit': pending_exit,
                'remaining_seconds': remaining,
                'active': pending_exit.get('active', False),
                'cancelled': pending_exit.get('cancelled', False),
                'current_btc_price': app.trading_bot.live_price
            })
        return jsonify({'success': True, 'pending_exit': None, 'active': False})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/cancel_exit_countdown', methods=['POST'])
def cancel_exit_countdown():
    """Cancel pending exit countdown from webpage"""
    try:
        if hasattr(app.trading_bot, 'pending_exit'):
            success = app.trading_bot.cancel_pending_exit()
            
            if success:
                # Send cancellation log to trade log
                log_message = "Exit countdown cancelled by user"
                app.trading_bot.log_message(log_message)
                
                return jsonify({'success': True, 'message': 'Exit cancelled successfully'})
            return jsonify({'success': False, 'error': 'No active exit to cancel'})
        return jsonify({'success': False, 'error': 'No pending exit found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Start monitor thread
monitor_thread = threading.Thread(target=trigger_order_monitor, daemon=True)
monitor_thread.start()
print("✅ Trigger order monitor thread started")

# ============ MAIN ENTRY POINT ============

if __name__ == '__main__':
    print("=" * 50)
    print("✅ Option Trading App starting on http://0.0.0.0:5001")
    print("💾 Using SQLite database for persistent storage")
    print("🤖 Telegram polling active - /btc commands will work")
    print("🔄 Auto BTC updates every 30 minutes to Telegram")
    print("=" * 50)
    app.run(debug=True, host='0.0.0.0', port=5001, use_reloader=False)