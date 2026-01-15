
import ccxt
import pandas as pd
import numpy as np
import time
from datetime import datetime
import os
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
import threading

class SmartMarketScanner:
    """
    優化版市場掃描器
    - 並發查詢提速 5-10x
    - 真實盤口數據（Order Book）
    - 精確手續費計算（區分 Maker/Taker）
    - 智能緩存策略
    """
    
    # 交易所手續費表 (VIP0 標準費率)
    FEE_SCHEDULE = {
        'binance': {'maker': 0.0002, 'taker': 0.0005},  # 0.02% / 0.05%
        'bybit': {'maker': 0.0001, 'taker': 0.0006},    # 0.01% / 0.06%
        'okx': {'maker': 0.0002, 'taker': 0.0005}       # 0.02% / 0.05%
    }
    
    def __init__(self, use_mock=False):
        self.use_mock = use_mock
        self.exchanges = {}
        self.history = {}
        self.cache = {}  # 緩存層
        self.cache_lock = threading.Lock()
        
        if not use_mock:
            self._initialize_exchanges()
    
    def _initialize_exchanges(self):
        """初始化交易所連接"""
        try:
            # Binance
            if os.getenv('BINANCE_API_KEY'):
                self.exchanges['binance'] = ccxt.binance({
                    'apiKey': os.getenv('BINANCE_API_KEY'),
                    'secret': os.getenv('BINANCE_SECRET'),
                    'enableRateLimit': True,
                    'options': {'defaultType': 'future'}
                })
            
            # Bybit
            if os.getenv('BYBIT_API_KEY'):
                self.exchanges['bybit'] = ccxt.bybit({
                    'apiKey': os.getenv('BYBIT_API_KEY'),
                    'secret': os.getenv('BYBIT_SECRET'),
                    'enableRateLimit': True,
                    'options': {'defaultType': 'linear'}
                })
            
            # OKX
            if os.getenv('OKX_API_KEY'):
                self.exchanges['okx'] = ccxt.okx({
                    'apiKey': os.getenv('OKX_API_KEY'),
                    'secret': os.getenv('OKX_SECRET'),
                    'password': os.getenv('OKX_PASSWORD'),
                    'enableRateLimit': True,
                    'options': {'defaultType': 'swap'}
                })
            
            print(f"✅ 初始化 {len(self.exchanges)} 個交易所")
        except Exception as e:
            print(f"⚠️ 初始化失敗: {e}")
    
    def get_top_volume_symbols(self, limit=30) -> List[str]:
        """獲取高交易量幣種（帶緩存）"""
        cache_key = 'top_symbols'
        
        # 檢查緩存（5分鐘有效）
        if cache_key in self.cache:
            cached_time, cached_data = self.cache[cache_key]
            if time.time() - cached_time < 300:
                return cached_data
        
        if self.use_mock:
            return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'ARB/USDT', 'OP/USDT']
        
        try:
            if 'binance' not in self.exchanges:
                return ['BTC/USDT', 'ETH/USDT']
            
            tickers = self.exchanges['binance'].fetch_tickers()
            
            # 過濾並排序
            valid_tickers = [
                t for t in tickers.values() 
                if '/USDT' in t['symbol'] 
                and 'BUSD' not in t['symbol']
                and ':USDT' not in t['symbol']  # 排除季度合約
                and t.get('quoteVolume', 0) > 0
            ]
            
            sorted_tickers = sorted(
                valid_tickers,
                key=lambda x: x['quoteVolume'],
                reverse=True
            )
            
            result = [t['symbol'] for t in sorted_tickers[:limit]]
            
            # 更新緩存
            with self.cache_lock:
                self.cache[cache_key] = (time.time(), result)
            
            return result
        except Exception as e:
            print(f"獲取幣種失敗: {e}")
            return ['BTC/USDT', 'ETH/USDT']
    
    def _fetch_orderbook_price(self, exchange_name: str, symbol: str, side: str) -> Dict:
        """
        獲取盤口最優價格
        side: 'long' (買入，看 ask) 或 'short' (賣出，看 bid)
        """
        try:
            exchange = self.exchanges[exchange_name]
            
            # OKX 符號轉換
            query_symbol = symbol
            if exchange_name == 'okx':
                query_symbol = f"{symbol.split('/')[0]}-USDT-SWAP"
            
            # 獲取訂單簿
            orderbook = exchange.fetch_order_book(query_symbol, limit=5)
            
            if side == 'long':
                # 做多：買入價格（ask，賣單最低價）
                if orderbook['asks']:
                    price = orderbook['asks'][0][0]  # 最優賣價
                    volume = orderbook['asks'][0][1]
                    # 計算前5檔總深度
                    depth = sum([ask[0] * ask[1] for ask in orderbook['asks'][:5]])
                else:
                    return None
            else:
                # 做空：賣出價格（bid，買單最高價）
                if orderbook['bids']:
                    price = orderbook['bids'][0][0]  # 最優買價
                    volume = orderbook['bids'][0][1]
                    depth = sum([bid[0] * bid[1] for bid in orderbook['bids'][:5]])
                else:
                    return None
            
            return {
                'price': price,
                'volume': volume,
                'depth': depth,
                'exchange': exchange_name,
                'symbol': symbol
            }
        except Exception as e:
            print(f"獲取 {exchange_name} {symbol} 盤口失敗: {e}")
            return None
    
    def _fetch_funding_rate(self, exchange_name: str, symbol: str) -> Optional[float]:
        """獲取資金費率"""
        try:
            exchange = self.exchanges[exchange_name]
            
            query_symbol = symbol
            if exchange_name == 'okx':
                query_symbol = f"{symbol.split('/')[0]}-USDT-SWAP"
            
            rate_info = exchange.fetch_funding_rate(query_symbol)
            return float(rate_info['fundingRate'])
        except:
            return None
    
    def _calculate_fees(self, long_ex: str, short_ex: str, assume_maker: bool = True) -> float:
        """
        計算總手續費
        assume_maker: True = 假設 50% Maker, False = 全 Taker
        """
        long_fee = self.FEE_SCHEDULE.get(long_ex, {'maker': 0.0002, 'taker': 0.0005})
        short_fee = self.FEE_SCHEDULE.get(short_ex, {'maker': 0.0002, 'taker': 0.0005})
        
        if assume_maker:
            # 混合模式：開倉 Taker，平倉 Maker
            total_fee = (
                long_fee['taker'] +   # 開多 (市價單)
                short_fee['taker'] +  # 開空 (市價單)
                long_fee['maker'] +   # 平多 (限價單)
                short_fee['maker']    # 平空 (限價單)
            )
        else:
            # 保守模式：全 Taker
            total_fee = (
                long_fee['taker'] * 2 +  # 開多+平多
                short_fee['taker'] * 2   # 開空+平空
            )
        
        return total_fee
    
    def scan_funding_opportunities(self, progress_callback=None) -> List[Dict]:
        """
        並發掃描套利機會
        """
        if self.use_mock:
            return self._generate_mock_opportunities()
        
        symbols = self.get_top_volume_symbols()
        opportunities = []
        
        # 並發查詢
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {}
            
            for symbol in symbols:
                future = executor.submit(self._scan_single_symbol, symbol)
                futures[future] = symbol
            
            completed = 0
            for future in as_completed(futures):
                completed += 1
                if progress_callback:
                    progress_callback(completed, len(symbols))
                
                try:
                    result = future.result()
                    if result:
                        opportunities.append(result)
                except Exception as e:
                    symbol = futures[future]
                    print(f"掃描 {symbol} 失敗: {e}")
        
        # 按 APR 排序
        return sorted(opportunities, key=lambda x: x['apr'], reverse=True)
    
    def _scan_single_symbol(self, symbol: str) -> Optional[Dict]:
        """掃描單個幣種（核心邏輯）"""
        try:
            # 1. 並發獲取所有交易所的資金費率
            rates = {}
            with ThreadPoolExecutor(max_workers=3) as executor:
                rate_futures = {
                    executor.submit(self._fetch_funding_rate, ex_name, symbol): ex_name
                    for ex_name in self.exchanges.keys()
                }
                
                for future in as_completed(rate_futures):
                    ex_name = rate_futures[future]
                    rate = future.result()
                    if rate is not None:
                        rates[ex_name] = rate
            
            if len(rates) < 2:
                return None
            
            # 2. 找出最高和最低費率
            sorted_rates = sorted(rates.items(), key=lambda x: x[1])
            min_ex, min_rate = sorted_rates[0]   # 做多方
            max_ex, max_rate = sorted_rates[-1]  # 做空方
            
            rate_diff = max_rate - min_rate
            apr = rate_diff * 3 * 365 * 100  # 每天3次 * 365天 * 100%
            
            # 3. 獲取真實盤口數據
            long_book = self._fetch_orderbook_price(min_ex, symbol, 'long')
            short_book = self._fetch_orderbook_price(max_ex, symbol, 'short')
            
            if not long_book or not short_book:
                return None
            
            long_price = long_book['price']   # 買入價（ask）
            short_price = short_book['price']  # 賣出價（bid）
            
            # 4. 計算價差成本
            if short_price > 0:
                spread_cost = (long_price - short_price) / short_price
            else:
                spread_cost = 0.01
            
            # 5. 計算手續費（混合模式）
            fee_cost = self._calculate_fees(min_ex, max_ex, assume_maker=True)
            
            # 6. 總成本
            total_cost = spread_cost + fee_cost
            
            # 7. 回本天數
            daily_yield = rate_diff * 3  # 每天收益
            
            if total_cost <= 0:
                breakeven_days = 0.0  # 立即盈利
            elif daily_yield > 0.000001:
                breakeven_days = total_cost / daily_yield
            else:
                breakeven_days = 999
            
            # 8. 深度（USD）
            depth = min(long_book['depth'], short_book['depth'])
            
            # 9. 穩定性（歷史波動率）
            if symbol not in self.history:
                self.history[symbol] = []
            self.history[symbol].append(rate_diff)
            if len(self.history[symbol]) > 50:
                self.history[symbol].pop(0)
            
            sigma = np.std(self.history[symbol]) if len(self.history[symbol]) > 5 else 0.0001
            
            return {
                'symbol': symbol,
                'long_ex': min_ex,
                'short_ex': max_ex,
                'long_price': long_price,
                'short_price': short_price,
                'apr': apr,
                'rate_diff': rate_diff,
                'spread': spread_cost * 100,
                'fees': fee_cost * 100,
                'total_cost': total_cost * 100,
                'breakeven_days': breakeven_days,
                'depth': depth,
                'sigma': sigma,
                'timestamp': datetime.now()
            }
        
        except Exception as e:
            print(f"掃描 {symbol} 出錯: {e}")
            return None
    
    def _generate_mock_opportunities(self) -> List[Dict]:
        """生成模擬數據"""
        return [
            {
                'symbol': 'BTC/USDT',
                'long_ex': 'binance',
                'short_ex': 'bybit',
                'long_price': 42150.5,
                'short_price': 42148.2,
                'apr': 25.8,
                'rate_diff': 0.0006,
                'spread': 0.005,
                'fees': 0.14,
                'total_cost': 0.145,
                'breakeven_days': 0.8,
                'depth': 8500000,
                'sigma': 0.00015,
                'timestamp': datetime.now()
            },
            {
                'symbol': 'ETH/USDT',
                'long_ex': 'okx',
                'short_ex': 'binance',
                'long_price': 2245.8,
                'short_price': 2245.5,
                'apr': 18.2,
                'rate_diff': 0.00042,
                'spread': 0.013,
                'fees': 0.14,
                'total_cost': 0.153,
                'breakeven_days': 1.2,
                'depth': 3200000,
                'sigma': 0.0002,
                'timestamp': datetime.now()
            }
        ]
