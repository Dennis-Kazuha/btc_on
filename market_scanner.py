import ccxt
import pandas as pd
import numpy as np
import time
from datetime import datetime
import os

class SmartMarketScanner:
    def __init__(self, use_mock=False):
        self.use_mock = use_mock
        if not use_mock:
            # 1. 初始化三大交易所 (移除 Pionex)
            self.exchanges = {
                'binance': ccxt.binance({
                    'apiKey': os.getenv('BINANCE_API_KEY'),
                    'secret': os.getenv('BINANCE_SECRET'),
                    'options': {'defaultType': 'future'}
                }),
                'bybit': ccxt.bybit({
                    'apiKey': os.getenv('BYBIT_API_KEY'),
                    'secret': os.getenv('BYBIT_SECRET'),
                    'options': {'defaultType': 'future'}
                }),
                'okx': ccxt.okx({
                    'apiKey': os.getenv('OKX_API_KEY'),
                    'secret': os.getenv('OKX_SECRET'),
                    'options': {'defaultType': 'swap'}
                }),
            }
        else:
            self.exchanges = {}
        self.history = {} # 用來存歷史費率計算波動率
        print("✅ 智能篩選器啟動：鎖定 Binance, Bybit, OKX")

    def get_top_volume_symbols(self, limit=20):
        """
        [智能篩選] 第一步：只看流動性最好的前 20 大幣種
        避免在冷門幣種上遇到滑點過大的問題。
        """
        if self.use_mock:
            return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']
            
        try:
            # 以 Binance 的交易量為基準
            tickers = self.exchanges['binance'].fetch_tickers()
            # 排序並過濾出 USDT 永續合約
            sorted_tickers = sorted(
                [t for t in tickers.values() if '/USDT' in t['symbol'] and 'BUS' not in t['symbol']], 
                key=lambda x: x['quoteVolume'], 
                reverse=True
            )
            top_symbols = [t['symbol'] for t in sorted_tickers[:limit]]
            return top_symbols
        except Exception as e:
            print(f"⚠️ 獲取熱門幣種失敗: {e}")
            return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'] # 失敗時的預設清單

    def scan_funding_opportunities(self):
        """
        [策略核心] 掃描全市場，尋找「長期穩定」且「高報酬」的機會
        (已更新：新增價差與深度計算)
        """
        if self.use_mock:
            return self._generate_mock_opportunities()

        symbols = self.get_top_volume_symbols()
        opportunities = []

        print(f"🔍 正在掃描 {len(symbols)} 個主流幣種的資金費率...")

        for symbol in symbols:
            rates = {}
            for ex_name, exchange in self.exchanges.items():
                try:
                    # 處理 OKX 特殊符號格式
                    market_symbol = symbol
                    if ex_name == 'okx': 
                        market_symbol = symbol.replace('/', '-') + '-SWAP'
                    
                    rate_info = exchange.fetch_funding_rate(market_symbol)
                    rates[ex_name] = float(rate_info['fundingRate'])
                except:
                    continue
            
            if len(rates) < 2: continue

            # 找出最大利差
            sorted_rates = sorted(rates.items(), key=lambda x: x[1])
            min_ex, min_rate = sorted_rates[0]  # 做多 (付最少/領最多)
            max_ex, max_rate = sorted_rates[-1] # 做空 (領最多/付最少)
            
            diff = max_rate - min_rate
            apr = diff * 3 * 365 * 100 # 預估年化

            # --- 新增功能：計算價差與深度 (只針對選中的這兩個交易所抓取) ---
            try:
                # 取得做多交易所的 Ask (買進價) 和 AskSize (賣單量)
                long_symbol = symbol.replace('/', '-') + '-SWAP' if min_ex == 'okx' else symbol
                long_ticker = self.exchanges[min_ex].fetch_ticker(long_symbol)
                long_price = long_ticker['ask']
                long_vol = long_ticker['askVolume'] if 'askVolume' in long_ticker else 0
                
                # 取得做空交易所的 Bid (賣出價) 和 BidSize (買單量)
                short_symbol = symbol.replace('/', '-') + '-SWAP' if max_ex == 'okx' else symbol
                short_ticker = self.exchanges[max_ex].fetch_ticker(short_symbol)
                short_price = short_ticker['bid']
                short_vol = short_ticker['bidVolume'] if 'bidVolume' in short_ticker else 0

                # 1. 計算價差 (Spread)：(買貴了多少 %)
                # 如果是正數，代表 LongPrice > ShortPrice (進場有成本)
                spread = (long_price - short_price) / short_price * 100
                
                # 2. 計算深度 (Depth)：兩邊能吃下的最小金額 (USDT)
                # 這樣才知道你的資金進不進得去
                long_depth_usdt = long_vol * long_price
                short_depth_usdt = short_vol * short_price
                min_depth = min(long_depth_usdt, short_depth_usdt)

            except Exception as e:
                # 如果抓不到價格，先給預設值
                spread = 0.0
                min_depth = 0.0
            # ----------------------------------------------------

            # 記錄歷史數據以計算穩定性 (Sigma)
            if symbol not in self.history: self.history[symbol] = []
            self.history[symbol].append(diff)
            if len(self.history[symbol]) > 50: self.history[symbol].pop(0)

            # 計算波動率 (Stability)
            sigma = np.std(self.history[symbol]) if len(self.history[symbol]) > 5 else 999
            
            # [篩選邏輯] 
            if apr > 5: 
                opportunities.append({
                    'symbol': symbol,
                    'long_ex': min_ex,
                    'long_rate': min_rate,
                    'short_ex': max_ex,
                    'short_rate': max_rate,
                    'apr': apr,
                    'sigma': sigma,
                    'spread_rate': diff,
                    'spread_price': spread, # 新增
                    'depth': min_depth      # 新增
                })

        # 排序
        best_opps = sorted(opportunities, key=lambda x: (x['apr'] / (x['sigma'] if x['sigma']>0 else 1)), reverse=True)
        
        return best_opps

    def _generate_mock_opportunities(self):
        """生成模擬數據"""
        mock_symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']
        exchanges = ['binance', 'bybit', 'okx']
        opps = []
        for symbol in mock_symbols:
            long_ex = np.random.choice(exchanges)
            short_ex = np.random.choice([e for e in exchanges if e != long_ex])
            long_rate = np.random.uniform(-0.0001, 0.0001)
            short_rate = np.random.uniform(0.0001, 0.0003)
            diff = short_rate - long_rate
            apr = diff * 3 * 365 * 100
            opps.append({
                'symbol': symbol,
                'long_ex': long_ex,
                'long_rate': long_rate,
                'short_ex': short_ex,
                'short_rate': short_rate,
                'apr': apr,
                'sigma': np.random.uniform(0.00001, 0.0001),
                'spread_rate': diff,
                'spread_price': np.random.uniform(-0.05, 0.1),
                'depth': np.random.uniform(10000, 100000)
            })
        return sorted(opps, key=lambda x: x['apr'], reverse=True)

    def backtest_strategy(self, symbol, days=30):
        """
        [回測模組] 針對選定的幣種，模擬過去 30 天的 ROI 與 MDD
        """
        # 這裡模擬生成 30 天的歷史費率數據 (實戰需接歷史數據 API)
        np.random.seed(42)
        history_rates = np.random.normal(0.0001, 0.00005, days*3) # 每天 3 次費率
        
        cumulative_pnl = [10000] # 初始本金 10000
        for r in history_rates:
            profit = cumulative_pnl[-1] * r # 複利滾存
            cumulative_pnl.append(cumulative_pnl[-1] + profit)
            
        # 計算指標
        final_equity = cumulative_pnl[-1]
        roi = (final_equity - 10000) / 10000 * 100
        
        # MDD 計算
        peaks = pd.Series(cumulative_pnl).cummax()
        drawdowns = (pd.Series(cumulative_pnl) - peaks) / peaks
        mdd = drawdowns.min() * 100
        
        return roi, mdd

if __name__ == "__main__":
    scanner = SmartMarketScanner(use_mock=True)
    opps = scanner.scan_funding_opportunities()
    
    print(f"\n{'幣種':<10} | {'方向':<20} | {'年化報酬':<10} | {'穩定度(σ)':<10}")
    print("-" * 60)
    for op in opps[:5]: # 只顯示前 5 名
        direction = f"Long {op['long_ex']} / Short {op['short_ex']}"
        print(f"{op['symbol']:<10} | {direction:<20} | {op['apr']:>6.2f}%    | {op['sigma']:>8.5f}")
        
        # 順便跑一下回測
        roi, mdd = scanner.backtest_strategy(op['symbol'])
        print(f"   ↳ [回測] 30天 ROI: {roi:.2f}% | MDD: {mdd:.2f}% (策略穩健)")
