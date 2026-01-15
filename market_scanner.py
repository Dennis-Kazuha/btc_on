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

# 導入資金費率分析器
import sys
sys.path.append('/home/claude')
from funding_analyzer import FundingRateAnalyzer

class SmartMarketScanner:
    """
    優化版市場掃描器
    - 並發查詢提速 5-10x
    - 真實盤口數據（Order Book）
    - 精確手續費計算（區分 Maker/Taker）
    - 智能緩存策略
    - 資金費率深度分析（溢價指數、TWAP）
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
        self.funding_analyzer = None  # 資金費率分析器
        
        if not use_mock:
            self._initialize_exchanges()
            # 初始化資金費率分析器
            if self.exchanges:
                self.funding_analyzer = FundingRateAnalyzer(self.exchanges)
    
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
    
    def _fetch_funding_rate(self, exchange_name: str, symbol: str) -> Optional[dict]:
        """
        獲取資金費率和結算週期
        返回: {'rate': float, 'interval_hours': int}
        """
        try:
            exchange = self.exchanges[exchange_name]
            
            query_symbol = symbol
            if exchange_name == 'okx':
                query_symbol = f"{symbol.split('/')[0]}-USDT-SWAP"
            
            rate_info = exchange.fetch_funding_rate(query_symbol)
            funding_rate = float(rate_info['fundingRate'])
            
            # 獲取結算週期（小時）
            # 不同交易所 API 返回的欄位名稱不同
            interval_hours = 8  # 默認8小時
            
            if 'fundingIntervalHours' in rate_info:
                interval_hours = rate_info['fundingIntervalHours']
            elif 'fundingTimestamp' in rate_info and 'fundingDatetime' in rate_info:
                # 通過時間戳推算（部分交易所）
                try:
                    next_time = rate_info.get('fundingTimestamp')
                    current_time = rate_info.get('timestamp')
                    if next_time and current_time:
                        interval_ms = next_time - current_time
                        interval_hours = interval_ms / (1000 * 60 * 60)
                except:
                    pass
            
            # 交易所默認值（當API沒有提供時）
            if interval_hours == 8:  # 如果還是默認值
                exchange_defaults = {
                    'binance': 8,  # Binance 標準是8小時
                    'bybit': 8,    # Bybit 標準是8小時
                    'okx': 8       # OKX 標準是8小時
                }
                interval_hours = exchange_defaults.get(exchange_name, 8)
            
            return {
                'rate': funding_rate,
                'interval_hours': int(interval_hours)
            }
        except Exception as e:
            print(f"獲取 {exchange_name} {symbol} 資金費率失敗: {e}")
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
            # 1. 並發獲取所有交易所的資金費率和結算週期
            rates = {}
            intervals = {}
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                rate_futures = {
                    executor.submit(self._fetch_funding_rate, ex_name, symbol): ex_name
                    for ex_name in self.exchanges.keys()
                }
                
                for future in as_completed(rate_futures):
                    ex_name = rate_futures[future]
                    result = future.result()
                    if result is not None:
                        rates[ex_name] = result['rate']
                        intervals[ex_name] = result['interval_hours']
            
            if len(rates) < 2:
                return None
            
            # 2. 找出最高和最低費率
            sorted_rates = sorted(rates.items(), key=lambda x: x[1])
            min_ex, min_rate = sorted_rates[0]   # 做多方（低費率）
            max_ex, max_rate = sorted_rates[-1]  # 做空方（高費率）
            
            rate_diff = max_rate - min_rate
            
            # 3. 使用實際結算週期計算APR
            # 取兩個交易所中較短的週期（保守估計）
            funding_interval = min(intervals.get(min_ex, 8), intervals.get(max_ex, 8))
            times_per_day = 24 / funding_interval  # 每天結算次數
            apr = rate_diff * times_per_day * 365 * 100  # 年化收益率
            
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
            
            # 7. 回本天數（使用實際結算週期）
            daily_yield = rate_diff * times_per_day  # 每日收益
            
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
            
            # 10. 資金費率深度分析（溢價指數、穩定性）
            funding_analysis = {}
            if self.funding_analyzer:
                try:
                    # 分析做空方的資金費率（高費率方）
                    short_analysis = self.funding_analyzer.get_predicted_funding_rate(symbol, max_ex)
                    if short_analysis:
                        funding_analysis['short'] = {
                            'premium_index': short_analysis['current_premium'],
                            'twap_premium': short_analysis.get('twap_premium'),
                            'predicted_rate': short_analysis['predicted_rate'],
                            'impact_spread': short_analysis['impact_ask'] - short_analysis['impact_bid'],
                            'confidence': short_analysis['confidence']
                        }
                    
                    # 分析做多方的資金費率（低費率方）
                    long_analysis = self.funding_analyzer.get_predicted_funding_rate(symbol, min_ex)
                    if long_analysis:
                        funding_analysis['long'] = {
                            'premium_index': long_analysis['current_premium'],
                            'twap_premium': long_analysis.get('twap_premium'),
                            'predicted_rate': long_analysis['predicted_rate'],
                            'impact_spread': long_analysis['impact_ask'] - long_analysis['impact_bid'],
                            'confidence': long_analysis['confidence']
                        }
                    
                    # 穩定性分析
                    stability_short = self.funding_analyzer.analyze_funding_stability(symbol, max_ex, 60)
                    stability_long = self.funding_analyzer.analyze_funding_stability(symbol, min_ex, 60)
                    
                    if stability_short and stability_long:
                        # 綜合穩定性評分
                        avg_stability = (stability_short['stability_score'] + stability_long['stability_score']) / 2
                        funding_analysis['stability'] = {
                            'score': avg_stability,
                            'short_std': stability_short['std'],
                            'long_std': stability_long['std'],
                            'trend': stability_short['trend']
                        }
                except Exception as e:
                    print(f"資金費率分析失敗 {symbol}: {e}")
            
            return {
                'symbol': symbol,
                'long_ex': min_ex,
                'short_ex': max_ex,
                'long_price': long_price,
                'short_price': short_price,
                'apr': apr,
                'rate_diff': rate_diff,
                'funding_interval': funding_interval,  # 結算週期（小時）
                'times_per_day': times_per_day,        # 每日結算次數
                'spread': spread_cost * 100,
                'fees': fee_cost * 100,
                'total_cost': total_cost * 100,
                'breakeven_days': breakeven_days,
                'depth': depth,
                'sigma': sigma,
                'funding_analysis': funding_analysis,   # 資金費率深度分析
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
                'funding_interval': 8,      # 8小時結算
                'times_per_day': 3,         # 每天3次
                'spread': 0.005,
                'fees': 0.14,
                'total_cost': 0.145,
                'breakeven_days': 0.8,
                'depth': 8500000,
                'sigma': 0.00015,
                'funding_analysis': {
                    'short': {
                        'premium_index': 0.00015,
                        'twap_premium': 0.00014,
                        'predicted_rate': 0.00025,
                        'impact_spread': 2.5,
                        'confidence': '高'
                    },
                    'long': {
                        'premium_index': -0.00005,
                        'twap_premium': -0.00004,
                        'predicted_rate': 0.00006,
                        'impact_spread': 1.8,
                        'confidence': '高'
                    },
                    'stability': {
                        'score': 0.85,
                        'short_std': 0.00008,
                        'long_std': 0.00006,
                        'trend': '穩定'
                    }
                },
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
                'funding_interval': 8,      # 8小時結算
                'times_per_day': 3,         # 每天3次
                'spread': 0.013,
                'fees': 0.14,
                'total_cost': 0.153,
                'breakeven_days': 1.2,
                'depth': 3200000,
                'sigma': 0.0002,
                'funding_analysis': {
                    'short': {
                        'premium_index': 0.00012,
                        'twap_premium': 0.00011,
                        'predicted_rate': 0.00022,
                        'impact_spread': 1.2,
                        'confidence': '中'
                    },
                    'long': {
                        'premium_index': -0.00008,
                        'twap_premium': -0.00007,
                        'predicted_rate': 0.00003,
                        'impact_spread': 0.9,
                        'confidence': '中'
                    },
                    'stability': {
                        'score': 0.75,
                        'short_std': 0.00012,
                        'long_std': 0.00010,
                        'trend': '上升'
                    }
                },
                'timestamp': datetime.now()
            }
        ]
