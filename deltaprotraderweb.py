# deltaprotraderweb.py
from datetime import datetime, timedelta
import time
import threading
import uuid
import requests
import json
import hashlib
import hmac
import urllib.parse
import socket
import os
import queue
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / 'userdata.env')

# TELEGRAM FUNCTION - CLASS KE BAHAR (YEH IMPORT KE LIYE HAI)
def send_telegram_alert(message, chat_id=None):
    """
    Telegram अलर्ट भेजता है।
    अगर chat_id नहीं दिया गया है तो default chat_id का उपयोग करता है।
    """
    token = '7956030237:AAHNzQejy0_q69NrVVGDr5erKmc5kbd2Apg'
    
    # अगर chat_id नहीं दिया गया तो default chat_id का उपयोग करें
    if chat_id is None:
        chat_id = '8008414806'
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram error: {str(e)}")
        return False

# ============ HELPER FUNCTIONS ============

def generate_signature(secret, message):
    """Generate HMAC SHA256 signature"""
    message = bytes(message, 'utf-8')
    secret = bytes(secret, 'utf-8')
    hash_obj = hmac.new(secret, message, hashlib.sha256)
    return hash_obj.hexdigest()

# ============ DELTA EXCHANGE API CLASS ============

class DeltaExchangeAPI:
    def __init__(self):
        self.api_key = os.getenv("DELTA_API_KEY", "DEFAULT_KEY")
        self.api_secret = os.getenv("DELTA_API_SECRET", "DEFAULT_SECRET")
        self.base_url = "https://api.india.delta.exchange"
        
    def generate_signature(self, method, endpoint, body=None, params=None):
        ts = str(int(time.time()))
        
        # Build the full path including query parameters
        if params:
            query_string = urllib.parse.urlencode(params, doseq=True)
            full_path = f"{endpoint}?{query_string}"
        else:
            full_path = endpoint
        
        message = method + ts + full_path
        
        if body:
            body_str = json.dumps(body, ensure_ascii=False)
            message += body_str
        
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return ts, signature, full_path

    # ============ EXISTING METHODS ============

    def get_option_data(self, symbol):
        """
        Delta Exchange से एक विशिष्ट ऑप्शन सिंबल के लिए रियल-टाइम डेटा (प्राइस और ग्रीक्स) प्राप्त करता है।
        """
        endpoint = "/v2/tickers"
        method = "GET"
        params = {"product_symbol": symbol}
        
        ts, signature, full_path = self.generate_signature(method, endpoint, params=params)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": ts
        }
        
        try:
            response = requests.get(
                self.base_url + full_path,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("result"):
                    ticker_data = data["result"]
                    # सुनिश्चित करें कि सभी आवश्यक फ़ील्ड मौजूद हैं
                    required_keys = ['mark_price', 'delta', 'gamma', 'theta', 'vega', 'rho']
                    if all(k in ticker_data for k in required_keys):
                        return {
                            "success": True,
                            "mark_price": float(ticker_data["mark_price"]),
                            "delta": float(ticker_data["delta"]),
                            "gamma": float(ticker_data["gamma"]),
                            "theta": float(ticker_data["theta"]),
                            "vega": float(ticker_data["vega"]),
                            "rho": float(ticker_data["rho"]),
                            "volatility": None,
                            "interest_rate": None
                        }
                return {"success": False, "error": "Option data not found or incomplete in API response."}
            else:
                error_msg = f"{response.status_code} - {response.text}"
                return {"success": False, "error": error_msg}
        except Exception as e:
            return {"success": False, "error": str(e)}
            
    def place_market_order(self, product_id, side, size):
        """
        Delta Exchange पर एक मार्केट ऑर्डर देता है।
        """
        endpoint = "/v2/orders"
        method = "POST"
        
        order_payload = {
            "product_id": product_id,
            "size": str(size),
            "side": side,
            "order_type": "market_order",
            "time_in_force": "gtc",
            "post_only": False,
            "reduce_only": False,
            "mmp": "disabled"
        }
        
        ts, signature, _ = self.generate_signature(method, endpoint, order_payload)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": ts
        }
        
        try:
            response = requests.post(
                self.base_url + endpoint,
                headers=headers,
                json=order_payload,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"{response.status_code} - {response.text}"
                return {"error": error_msg, "success": False}
                
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def place_stop_loss_order(self, product_id, side, size, stop_price):
        """
        Stop Loss ऑर्डर प्लेस करता है।
        """
        endpoint = "/v2/orders"
        method = "POST"
        
        order_payload = {
            "product_id": product_id,
            "size": str(size),
            "side": side,
            "order_type": "market_order",
            "stop_order_type": "stop_loss_order",
            "stop_price": str(stop_price),
            "time_in_force": "gtc",
            "reduce_only": True,
            "mmp": "disabled"
        }
        
        ts, signature, _ = self.generate_signature(method, endpoint, order_payload)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": ts
        }
        
        try:
            response = requests.post(
                self.base_url + endpoint,
                headers=headers,
                json=order_payload,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"{response.status_code} - {response.text}"
                return {"error": error_msg, "success": False}
                
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def place_limit_order(self, product_id, side, size, limit_price):
        """
        Limit ऑर्डर प्लेस करता है।
        """
        endpoint = "/v2/orders"
        method = "POST"
        
        order_payload = {
            "product_id": product_id,
            "size": str(size),
            "side": side,
            "order_type": "limit_order",
            "limit_price": str(limit_price),
            "time_in_force": "gtc",
            "reduce_only": False
        }
        
        ts, signature, _ = self.generate_signature(method, endpoint, order_payload)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": ts
        }
        
        try:
            response = requests.post(
                self.base_url + endpoint,
                headers=headers,
                json=order_payload,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"HTTP {response.status_code}", "success": False}
                
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def get_margined_positions(self):
        """
        मार्जिन्ड पोजीशन्स प्राप्त करता है।
        """
        endpoint = "/v2/positions/margined"
        method = "GET"
        
        ts, signature, full_path = self.generate_signature(method, endpoint)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": ts
        }
        
        try:
            response = requests.get(
                self.base_url + full_path,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "result": data.get('result', [])
                }
            else:
                error_msg = f"{response.status_code} - {response.text}"
                return {"error": error_msg, "success": False}
                
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def get_open_orders(self):
        """
        ओपन ऑर्डर्स प्राप्त करता है।
        """
        endpoint = "/v2/orders"
        method = "GET"
        params = {"open": "true"}
        
        ts, signature, full_path = self.generate_signature(method, endpoint, params=params)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": ts
        }
        
        try:
            response = requests.get(
                self.base_url + full_path,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "result": data.get('result', [])
                }
            else:
                error_msg = f"{response.status_code} - {response.text}"
                return {"error": error_msg, "success": False}
                
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def cancel_all_orders(self, product_id=None):
        """
        सभी ऑर्डर्स कैंसल करता है।
        """
        endpoint = "/v2/orders"
        method = "DELETE"
        
        params = {}
        if product_id:
            params["product_id"] = product_id
        
        ts, signature, full_path = self.generate_signature(method, endpoint, params=params)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": ts
        }
        
        try:
            response = requests.delete(
                self.base_url + full_path,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"{response.status_code} - {response.text}"
                return {"error": error_msg, "success": False}
                
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def square_off_all(self):
        """
        सभी पोजीशन्स बंद करता है।
        """
        endpoint = "/v2/positions/close_all"
        method = "POST"
        
        order_payload = {
            "close_all_portfolio": True,
            "close_all_isolated": True,
            "user_id": 0
        }
        
        ts, signature, _ = self.generate_signature(method, endpoint, order_payload)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": ts
        }
        
        try:
            response = requests.post(
                self.base_url + endpoint,
                headers=headers,
                json=order_payload,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"{response.status_code} - {response.text}"
                return {"error": error_msg, "success": False}
                
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def cancel_order(self, order_id):
        """
        एक विशिष्ट ऑर्डर कैंसल करता है।
        """
        endpoint = f"/v2/orders/{order_id}"
        method = "DELETE"
        
        ts, signature, full_path = self.generate_signature(method, endpoint)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": ts
        }
        
        try:
            response = requests.delete(
                self.base_url + full_path,
                headers=headers,
                timeout=5
            )
            
            if response.status_code == 200:
                return {"success": True}
            else:
                error_msg = f"{response.status_code} - {response.text}"
                return {"error": error_msg, "success": False}
                
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def get_wallet_balances(self):
        """Delta Exchange से wallet balances प्राप्त करता है"""
        endpoint = "/v2/wallet/balances"
        method = "GET"
        
        ts, signature, full_path = self.generate_signature(method, endpoint)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": ts
        }
        
        try:
            response = requests.get(
                self.base_url + full_path,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return {
                        "success": True,
                        "result": data.get("result", [])
                    }
                else:
                    return {"success": False, "error": data.get('error', 'Unknown error')}
            else:
                error_msg = f"{response.status_code} - {response.text}"
                return {"success": False, "error": error_msg}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ============ NEW ACCURATE PNL METHODS ============
    
    def get_product_ticker(self, product_id):
        """
        Product का current mark price fetch करता है
        """
        try:
            url = f"{self.base_url}/v2/tickers/{product_id}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success') and data.get('result'):
                    return float(data['result'].get('mark_price', 0))
            return None
        except Exception as e:
            return None

    def get_unrealized_pnl_calculated(self):
        """
        Open positions का total unrealized PNL calculate करता है
        """
        try:
            method = 'GET'
            timestamp = str(int(time.time()))
            path = '/v2/positions/margined'
            url = f'{self.base_url}{path}'
            query_string = ''
            payload = ''
            
            signature_data = method + timestamp + path + query_string + payload
            signature = generate_signature(self.api_secret, signature_data)
            
            req_headers = {
                'api-key': self.api_key,
                'timestamp': timestamp,
                'signature': signature,
                'User-Agent': 'python-rest-client',
                'Content-Type': 'application/json'
            }
            
            response = requests.request(
                method, url, data=payload, params={}, timeout=10, headers=req_headers
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('success') and data.get('result') and len(data['result']) > 0:
                    positions = data['result']
                    total_unrealized_pnl = 0.0
                    
                    for pos in positions:
                        product_id = pos.get('product_id')
                        size = float(pos.get('size', 0))
                        entry_price = float(pos.get('entry_price', 0))
                        
                        # Get current mark price
                        mark_price = self.get_product_ticker(product_id)
                        
                        if mark_price and size != 0:
                            # Calculate unrealized PNL
                            unrealized_pnl = (mark_price - entry_price) * size
                            total_unrealized_pnl += unrealized_pnl
                    
                    return round(total_unrealized_pnl, 2) if total_unrealized_pnl != 0 else 0.0
                else:
                    return 0.0
            else:
                return 0.0
                
        except Exception as e:
            return 0.0

    def get_realized_pnl_from_csv(self):
        """
        Last closed order का realized PNL return करता है (CSV endpoint से)
        """
        try:
            method = 'GET'
            timestamp = str(int(time.time()))
            path = '/v2/orders/history/download/csv'
            url = f'{self.base_url}{path}'
            
            end_time = int(time.time() * 1000000)
            start_time = end_time - (30 * 24 * 60 * 60 * 1000000)
            
            query_string = f'?start_time={start_time}&end_time={end_time}'
            payload = ''
            
            signature_data = method + timestamp + path + query_string + payload
            signature = generate_signature(self.api_secret, signature_data)
            
            req_headers = {
                'api-key': self.api_key,
                'timestamp': timestamp,
                'signature': signature,
                'User-Agent': 'python-rest-client',
                'Content-Type': 'application/json'
            }
            
            query = {"start_time": start_time, "end_time": end_time}
            
            response = requests.request(
                method, url, data=payload, params=query, timeout=10, headers=req_headers
            )
            
            if response.status_code == 200:
                import csv
                from io import StringIO
                
                csv_content = response.content.decode('utf-8')
                csv_reader = csv.DictReader(StringIO(csv_content))
                rows = list(csv_reader)
                
                if rows:
                    # Find the most recent closed order
                    closed_orders = [r for r in rows if r.get('Status') == 'closed']
                    if closed_orders:
                        # Get the most recent closed order (first in the list is most recent)
                        last_closed = closed_orders[0]
                        realized_pnl_str = last_closed.get('Realised P&L', '0')
                        
                        # Convert to float (remove commas if any)
                        try:
                            realized_pnl = float(realized_pnl_str.replace(',', ''))
                            return round(realized_pnl, 2)
                        except:
                            return 0.0
                return 0.0
            else:
                return 0.0
                
        except Exception as e:
            return 0.0

# ============ TRADING BOT CLASS ============

class TradingBot:
    def __init__(self):
        # Initialize API
        self.api = DeltaExchangeAPI()
        
        # Log API key status for debugging
        if self.api.api_key:
            print(f"API key loaded: {self.api.api_key[:5]}...")
        else:
            print("API key not loaded! Check userdata.env")
                
        # Variables
        self.live_price = 0.0
        self.previous_price = 0.0
        self.price_change = 0.0
        self.price_change_percent = 0.0
        self.logs = []
        
        # Missing attributes that option_trading_app.py expects
        self.previous_day_close = None
        self.current_ip = "Checking..."
        self.ip_verified = False
        self.position = {}
        self.price_vs_previous_close = "0.00%"
        
        # Index exit parameters - UPDATED STRUCTURE
        self.index_exit_params = {
            'above': {'price': None, 'type': None},  # type: 'sl', 'target', or None
            'below': {'price': None, 'type': None}
        }
        
        # BTC price alerts for trigger orders
        self.btc_price_alerts = []
        self.alerts_lock = threading.Lock()
        self.stopped = False
        
        # Active orders tracking
        self.active_orders = {}
        self.position_orders = {'SL': None, 'Target': None}
        
        # **ADD THIS: Initialize pending exit structure**
        self.pending_exit = {
            'active': False,
            'countdown': 7,
            'end_time': None,
            'level': None,
            'exit_type': None,
            'trigger_price': None,
            'cancelled': False,
            'trigger_reason': None
        }
        
        # अलर्ट चेकिंग के लिए नया थ्रेड शुरू करें
        self.alerts_thread = threading.Thread(target=self._check_price_alerts_loop, daemon=True)
        self.alerts_thread.start()
        
        # Schedule daily update at 05:30 AM IST
        threading.Thread(target=self.auto_daily_refresh, daemon=True).start()
        
        # Start threads
        threading.Thread(target=self.update_live_price, daemon=True).start()
        threading.Thread(target=self.fetch_current_ip, daemon=True).start()
        threading.Thread(target=self.verify_ip_periodically, daemon=True).start()
        threading.Thread(target=self.initialize_previous_close, daemon=True).start()
        
        self.log_message("TradingBot initialized successfully.")

    # ============ NEW ACCURATE PNL METHODS ============
    
    def get_pnl_summary(self):
        """
        नया accurate PNL summary return करता है (working code integration के साथ)
        """
        try:
            # Get active positions count
            positions_response = self.api.get_margined_positions()
            active_positions = 0
            
            if positions_response and positions_response.get('success'):
                positions = positions_response.get('result', [])
                for position in positions:
                    size = float(position.get('size', 0))
                    if size != 0:
                        active_positions += 1
            
            # Get unrealized PNL from calculated method
            total_unrealized_pnl = self.api.get_unrealized_pnl_calculated()
            
            # Get realized PNL from CSV
            last_trade_realized_pnl = self.api.get_realized_pnl_from_csv()
            
            return {
                "success": True,
                "active_positions": active_positions,
                "total_unrealized_pnl": total_unrealized_pnl,
                "last_trade_realized_pnl": last_trade_realized_pnl,
                "total_pnl": last_trade_realized_pnl + total_unrealized_pnl
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_accurate_wallet_info(self):
        """सही wallet information प्राप्त करता है"""
        try:
            response = self.api.get_wallet_balances()
            
            if response and response.get('success'):
                wallets = response.get('result', [])
                usd_balance = 0.0
                usdt_balance = 0.0
                
                for wallet in wallets:
                    asset_symbol = wallet.get('asset_symbol', '')
                    available_balance = float(wallet.get('available_balance', 0))
                    
                    if asset_symbol == 'USD':
                        usd_balance = available_balance
                    elif asset_symbol == 'USDT':
                        usdt_balance = available_balance
                
                # Prefer USD, fallback to USDT
                balance = usd_balance if usd_balance > 0 else usdt_balance
                asset = 'USD' if usd_balance > 0 else 'USDT' if usdt_balance > 0 else 'USD'
                
                return {
                    'success': True,
                    'balance': balance,
                    'asset': asset,
                    'usd_balance': usd_balance,
                    'usdt_balance': usdt_balance
                }
            else:
                error = response.get('error', 'Unknown error') if response else "No response"
                return {'success': False, 'error': error}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ============ EXISTING METHODS ============
    
    def auto_daily_refresh(self):
        """Automatically refresh previous day close at 05:30 AM IST daily"""
        while not self.stopped:
            try:
                # Get current UTC time
                utc_now = datetime.utcnow()
                
                # Convert to IST (UTC + 5:30)
                ist_now = utc_now + timedelta(hours=5, minutes=30)
                
                # Check if it's 05:30 AM IST
                if ist_now.hour == 5 and ist_now.minute == 30:
                    self.log_message("05:30 AM IST - Auto-refreshing previous day close...")
                    
                    # Update previous day close
                    success = self.update_previous_day_close()
                    
                    if success:
                        self.log_message(f"Auto-refresh: Previous day close updated to ${self.previous_day_close:,.2f}")
                        
                        # Send Telegram notification
                        message = (
                            f"🔄 <b>Daily Auto-Refresh</b>\n\n"
                            f"Previous day close updated: <b>${self.previous_day_close:,.2f}</b>\n"
                            f"Time: {ist_now.strftime('%H:%M')} IST\n"
                            f"New day started for 24h change calculation."
                        )
                        send_telegram_alert(message)
                    
                    # Sleep for 1 hour to avoid multiple triggers
                    time.sleep(3600)
                else:
                    # Sleep for 1 minute and check again
                    time.sleep(60)
                    
            except Exception as e:
                self.log_message(f"Auto-refresh error: {str(e)}")
                time.sleep(300)
    
    def is_index_exit_active(self):
        """
        Check if index-based exit is currently active
        """
        above_data = self.index_exit_params.get('above')
        below_data = self.index_exit_params.get('below')
        
        return (above_data and above_data.get('price') is not None) or \
               (below_data and below_data.get('price') is not None)

    def start_exit_countdown(self, level, exit_type, trigger_price, trigger_reason):
        """
        Start 7-second countdown before executing exit (WEBPAGE ONLY)
        """
        self.pending_exit = {
            'active': True,
            'countdown': 7,
            'end_time': time.time() + 7,
            'level': level,
            'exit_type': exit_type,
            'trigger_price': trigger_price,
            'cancelled': False,
            'trigger_reason': trigger_reason
        }
        
        # Log but DON'T send Telegram notification for countdown
        self.log_message(f"Exit countdown started for {level} level at {trigger_price} ({exit_type})")
        self.log_message(f"Trigger reason: {trigger_reason}")

    def cancel_pending_exit(self):
        """
        Cancel the pending exit countdown (WEBPAGE ONLY)
        """
        if self.pending_exit['active'] and not self.pending_exit['cancelled']:
            self.pending_exit['cancelled'] = True
            self.pending_exit['active'] = False
            
            self.log_message(f"Pending exit cancelled by user")
            return True
        return False
    
    def execute_pending_exit(self):
        """
        Execute the pending exit after countdown
        """
        if not self.pending_exit['active'] or self.pending_exit['cancelled']:
            return
        
        # Get current price for the message
        current_price = self.live_price
        
        # Prepare exit details
        exit_details = {
            'triggered': True,
            'message': f"Exit {self.pending_exit['level']} level triggered after countdown",
            'exit_type': self.pending_exit['exit_type'],
            'level': self.pending_exit['level'],
            'price': current_price,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'trigger_reason': self.pending_exit['trigger_reason']
        }
        
        # Log the execution
        self.log_message(f"Executing exit after countdown: {self.pending_exit}")
        
        # 1. Exit all positions (मूल काम)
        self.exit_all_positions(exit_details)
        
        # 2. IMPORTANT FIX: Reset the index exit levels
        self.set_index_exit_params(above_price=None, below_price=None, above_type=None, below_type=None)
        self.log_message("✅ Index exit levels cleared after automatic exit.")
        
        # 3. Clear the pending exit structure
        self.pending_exit = {
            'active': False,
            'countdown': 7,
            'end_time': None,
            'level': None,
            'exit_type': None,
            'trigger_price': None,
            'cancelled': False,
            'trigger_reason': None
        }

    
    
    def initialize_previous_close(self):
        """Initialize previous day close in background"""
        self.update_previous_day_close()
    
    def update_previous_day_close(self):
        """Fetch previous day's closing price from Delta Exchange"""
        try:
            # Get current UTC time
            now = datetime.utcnow()
            
            # Calculate yesterday's date at midnight UTC
            utc_yesterday = datetime(
                year=now.year,
                month=now.month,
                day=now.day,
                hour=0,
                minute=0,
                second=0
            ) - timedelta(days=1)
            
            # Calculate today's date at midnight UTC
            utc_today = datetime(
                year=now.year,
                month=now.month,
                day=now.day,
                hour=0,
                minute=0,
                second=0
            )
            
            # Convert to timestamps
            start_ts = int(utc_yesterday.timestamp())
            end_ts = int(utc_today.timestamp())
            
            # Fetch daily candles from Delta Exchange
            response = requests.get(
                "https://api.india.delta.exchange/v2/history/candles",
                params={
                    "symbol": "BTCUSD",
                    "resolution": "1d",
                    "start": start_ts,
                    "end": end_ts
                },
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("result") and len(data["result"]) > 0:
                    self.previous_day_close = float(data["result"][0]["close"])
                    self.log_message(f"Loaded previous day close: ${self.previous_day_close:,.2f}")
                    return True
        except Exception as e:
            self.log_message(f"Error loading previous close: {str(e)}")
        return False
    
    def fetch_current_ip(self):
        """Fetch and display current public IP address"""
        while not self.stopped:
            try:
                # Try to get public IP
                try:
                    response = requests.get("https://api64.ipify.org?format=json", timeout=5)
                    if response.status_code == 200:
                        ip_data = response.json()
                        self.current_ip = ip_data.get("ip", "Unknown")
                    else:
                        self.current_ip = "Failed to fetch"
                except:
                    # Fallback to socket method
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    self.current_ip = s.getsockname()[0]
                    s.close()
                
                # Update every 5 minutes
                time.sleep(300)
            except Exception as e:
                self.current_ip = "Error fetching"
                time.sleep(60)
    
    def verify_ip_periodically(self):
        """Verify IP is whitelisted by checking positions or orders instead of wallet"""
        while not self.stopped:
            try:
                # Try checking open orders first (lightweight call)
                response = self.api.get_open_orders()
                
                # If orders check fails, try positions as fallback
                if not response or not response.get('success'):
                    response = self.api.get_margined_positions()
                
                if response and response.get('success'):
                    self.ip_verified = True
                else:
                    self.ip_verified = False
                    
                    # Send Telegram alert if IP verification fails
                    error = response.get('error', 'Unknown error') if response else "No response"
                    telegram_msg = (
                        f"<b>⚠️ IP Verification Failed</b>\n"
                        f"<b>Error:</b> {error}\n"
                        f"<b>Current IP:</b> {self.current_ip}\n"
                        f"<b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
                    )
                    threading.Thread(target=lambda: send_telegram_alert(telegram_msg), daemon=True).start()
                
                # Check every 5 minutes
                time.sleep(300)
            except Exception as e:
                self.log_message(f"IP verification error: {str(e)}")
                time.sleep(60)
    
    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)
        # Keep last 100 logs
        if len(self.logs) > 100:
            self.logs.pop(0)
        print(log_entry)
    
    def fetch_btc_price(self):
        """
        BTC की वर्तमान कीमत प्राप्त करता है।
        """
        url = "https://cdn.india.deltaex.org/v2/tickers/BTCUSD"
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("result") and data["result"].get("mark_price") is not None:
                    return float(data["result"]["mark_price"])
            return None
        except Exception as e:
            self.log_message(f"Error fetching BTC price: {e}")
            return None
    
    def fetch_btc_price_fallback(self):
        """
        Fallback method for BTC price fetching
        """
        try:
            response = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return float(data['price'])
            return None
        except Exception as e:
            self.log_message(f"Binance fallback error: {e}")
            return None
    
    def update_live_price(self):
        """
        BTC की कीमत अपडेट करता है।
        """
        while not self.stopped:
            try:
                # Store previous price for change calculation
                self.previous_price = self.live_price
                
                # Get new price
                btc_price = self.fetch_btc_price()
                if btc_price is None:
                    btc_price = self.fetch_btc_price_fallback()
                
                if btc_price is not None:
                    self.live_price = btc_price
                    
                    # Calculate price change
                    if self.previous_price > 0:
                        self.price_change = self.live_price - self.previous_price
                        self.price_change_percent = (self.price_change / self.previous_price) * 100
                    
                    # Calculate comparison with previous day close
                    if self.previous_day_close and self.previous_day_close > 0:
                        change_vs_previous = self.live_price - self.previous_day_close
                        percent_change = (change_vs_previous / self.previous_day_close) * 100
                        self.price_vs_previous_close = f"{percent_change:.2f}%"
                
                time.sleep(2)
                
            except Exception as e:
                self.log_message(f"Price update error: {str(e)}")
                time.sleep(5)
    
    def _check_price_alerts_loop(self):
        """
        बैकग्राउंड में प्राइस अलर्ट और इंडेक्स एग्जिट की जाँच करता है।
        """
        while not self.stopped:
            try:
                current_price = self.live_price
                if not current_price:
                    time.sleep(5)
                    continue
                
                # Check if there's a pending exit countdown (WEBPAGE ONLY)
                if self.pending_exit['active'] and not self.pending_exit['cancelled']:
                    current_time = time.time()
                    
                    # Check if countdown has finished
                    if current_time >= self.pending_exit['end_time']:
                        self.execute_pending_exit()
                    else:
                        # Just wait and continue checking
                        time.sleep(1)
                        continue
                
                # इंडेक्स बेस्ड एग्जिट की जाँच करें
                above_data = self.index_exit_params.get('above')
                below_data = self.index_exit_params.get('below')
                
                triggered = False
                trigger_reason = ""
                exit_type = ""  # 'sl', 'target', or ''
                level = ""  # 'above' or 'below'
                trigger_price = None
                
                # Above level check
                if above_data and above_data.get('price') is not None and current_price >= above_data['price']:
                    triggered = True
                    level = 'above'
                    trigger_price = above_data['price']
                    level_type = above_data.get('type', '')
                    if level_type == 'sl':
                        trigger_reason = f"Stop Loss Hit! BTC price ${current_price:.2f} >= ${above_data['price']} (Above)"
                        exit_type = 'sl'
                    elif level_type == 'target':
                        trigger_reason = f"Target Hit! BTC price ${current_price:.2f} >= ${above_data['price']} (Above)"
                        exit_type = 'target'
                    else:
                        trigger_reason = f"Exit Above triggered! BTC price ${current_price:.2f} >= ${above_data['price']}"
                    
                    self.log_message(f"Index exit triggered (Above): {trigger_reason}")
                
                # Below level check (only if above not triggered)
                if not triggered and below_data and below_data.get('price') is not None and current_price <= below_data['price']:
                    triggered = True
                    level = 'below'
                    trigger_price = below_data['price']
                    level_type = below_data.get('type', '')
                    if level_type == 'sl':
                        trigger_reason = f"Stop Loss Hit! BTC price ${current_price:.2f} <= ${below_data['price']} (Below)"
                        exit_type = 'sl'
                    elif level_type == 'target':
                        trigger_reason = f"Target Hit! BTC price ${current_price:.2f} <= ${below_data['price']} (Below)"
                        exit_type = 'target'
                    else:
                        trigger_reason = f"Exit Below triggered! BTC price ${current_price:.2f} <= ${below_data['price']}"
                    
                    self.log_message(f"Index exit triggered (Below): {trigger_reason}")
                
                if triggered and not self.pending_exit['active']:
                    # Start 7-second countdown (WEBPAGE ONLY)
                    self.start_exit_countdown(level, exit_type, trigger_price, trigger_reason)
                    
                    # Log for debugging
                    self.log_message(f"Exit countdown started for {level} at ${trigger_price}")
                    
                    # Wait for countdown to finish
                    time.sleep(7)
                    
            except Exception as e:
                self.log_message(f"Error in alert checking loop: {e}")
                time.sleep(10)
    
    def add_btc_alert(self, price, condition):
        """
        BTC प्राइस अलर्ट जोड़ता है।
        """
        with self.alerts_lock:
            alert_id = str(uuid.uuid4())
            self.btc_price_alerts.append({'id': alert_id, 'price': float(price), 'condition': condition})
            self.log_message(f"New BTC alert set: {condition} {price}")
        return {'success': True, 'id': alert_id}
    
    def get_btc_alerts(self):
        """
        सभी BTC प्राइस अलर्ट्स प्राप्त करता है।
        """
        with self.alerts_lock:
            return self.btc_price_alerts
    
    def delete_btc_alert(self, alert_id):
        """
        एक BTC प्राइस अलर्ट डिलीट करता है।
        """
        with self.alerts_lock:
            initial_len = len(self.btc_price_alerts)
            self.btc_price_alerts = [a for a in self.btc_price_alerts if a['id'] != alert_id]
            if len(self.btc_price_alerts) < initial_len:
                self.log_message(f"BTC alert {alert_id} deleted.")
                return {'success': True}
        return {'success': False, 'error': 'Alert not found'}
    
    def set_index_exit_params(self, above_price=None, below_price=None, above_type=None, below_type=None):
        """
        इंडेक्स एक्जिट पैरामीटर्स सेट करता है - UPDATED VERSION।
        type: 'sl', 'target', or None
        """
        try:
            if above_price is not None:
                self.index_exit_params['above']['price'] = float(above_price)
                self.index_exit_params['above']['type'] = above_type
            else:
                self.index_exit_params['above'] = {'price': None, 'type': None}
                
            if below_price is not None:
                self.index_exit_params['below']['price'] = float(below_price)
                self.index_exit_params['below']['type'] = below_type
            else:
                self.index_exit_params['below'] = {'price': None, 'type': None}
                
            self.log_message(f"Index exit levels updated: Above={self.index_exit_params['above']}, Below={self.index_exit_params['below']}")
            return {'success': True}
        except Exception as e:
            self.log_message(f"Error setting index exit params: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_position_details(self):
        """
        करंट पोजीशन डिटेल्स प्राप्त करता है।
        """
        try:
            positions = self.api.get_margined_positions()
            if positions and positions.get('success'):
                for position in positions['result']:
                    size = float(position.get("size", 0))
                    if size != 0:
                        entry_price = float(position.get("entry_price", 0))
                        side = "buy" if size > 0 else "sell"
                        self.position = {
                            "size": abs(size),
                            "entry_price": entry_price,
                            "side": side
                        }
                        return self.position
            self.position = {}
            return None
        except Exception as e:
            self.log_message(f"Error getting position details: {str(e)}")
            return None
    
    def exit_all_positions(self, exit_details=None):
        """
        सभी पोजीशन्स और ऑर्डर्स बंद करता है।
        """
        try:
            # Log exit details
            if exit_details:
                self.log_message(f"Exit triggered: {exit_details.get('message', 'No details')}")
                
            # सभी ऑर्डर्स कैंसल करें
            try:
                open_orders_response = self.api.get_open_orders()
                if open_orders_response and open_orders_response.get('success'):
                    open_orders = open_orders_response.get('result', [])
                    for order in open_orders:
                        order_id = order.get('id')
                        if order_id:
                            self.api.cancel_order(order_id)
                            self.log_message(f"Cancelled order: {order_id}")
            except Exception as e:
                self.log_message(f"Error cancelling orders: {str(e)}")
                
            # सभी पोजीशन्स बंद करें
            close_response = self.api.square_off_all()
            if close_response and "error" not in close_response:
                self.log_message("All positions closed successfully")
                
                # Send Telegram notification ONLY when actually executed (not during countdown)
                if exit_details and exit_details.get('exit_type'):
                    if exit_details['exit_type'] == 'sl':
                        notification_message = f"🔴 <b>STOP LOSS HIT!</b>\n"
                    elif exit_details['exit_type'] == 'target':
                        notification_message = f"🟢 <b>TARGET HIT!</b>\n"
                    else:
                        notification_message = f"⚠️ <b>EXIT EXECUTED!</b>\n"
                    
                    notification_message += f"<b>Reason:</b> {exit_details.get('trigger_reason', 'Index Exit')}\n"
                    notification_message += f"<b>BTC Price:</b> ${exit_details.get('price', 0):.2f}\n"
                    notification_message += f"<b>Time:</b> {datetime.now().strftime('%H:%M:%S')}\n"
                    notification_message += "All positions closed and orders cancelled."
                    
                    # Send Telegram notification
                    threading.Thread(target=lambda: send_telegram_alert(notification_message), daemon=True).start()
                
            else:
                error = close_response.get('error', 'Unknown error') if close_response else "No response"
                self.log_message(f"Close Positions Error: {error}")
                
            # Reset position orders
            self.position_orders = {'SL': None, 'Target': None}
            self.active_orders = {}
            self.position = {}
            # ✅ NEW ADDITION: If this exit was triggered by index levels, clear them.
            if exit_details and 'level' in exit_details:
                self.set_index_exit_params(above_price=None, below_price=None, above_type=None, below_type=None)
                self.log_message("✅ Index exit levels cleared via exit_all_positions.")
    
        except Exception as e:
            self.log_message(f"Exit All Error: {str(e)}")


    # ============ COMPATIBILITY METHODS ============
    
    def get_pnl_info(self):
        """
        पुराने method के लिए compatibility (get_pnl_summary का alias)
        """
        return self.get_pnl_summary()
    
    def get_option_greeks(self, symbol):
        """
        Option के Greeks प्राप्त करता है।
        """
        return self.api.get_option_data(symbol)
    
    def place_option_order(self, product_id, side, size):
        """
        Option का ऑर्डर प्लेस करता है।
        """
        return self.api.place_market_order(product_id, side, size)
    
    def send_telegram_notification(self, message):
        """
        Wrapper method for telegram alerts to maintain backward compatibility
        """
        return send_telegram_alert(message)
    
    def stop(self):
        """
        बॉट के सभी चल रहे थ्रेड्स को रोकने के लिए।
        """
        self.stopped = True
        self.log_message("TradingBot stopping all threads...")