import time
import threading
from market_scanner import SmartMarketScanner
from risk_guard import DynamicRiskGuard

def run_risk_monitor(guard):
    """
    [線程 1] 專注於保命：5秒級監控 (不間斷)
    """
    while True:
        # print("\n[5s 監控] -------------------------")
        try:
            guard.update_states() 
            # 讓 guard 內部只在「有狀況」時才 print，平常保持安靜
            triggered = guard.check_margin_health() 
            if not triggered:
                # 可以在這裡印一個小點點，代表還活著就好
                # print(".", end="", flush=True) 
                pass
        except Exception as e:
            print(f"監控異常: {e}")
        time.sleep(5)

def run_market_scan(scanner, guard):
    """
    [線程 2] 專注於賺錢：每分鐘掃描一次最佳機會 + 資產平衡
    """
    while True:
        print("\n[市場掃描] =========================")
        print(f"🕒 掃描時間: {time.strftime('%H:%M:%S')}")
        try:
            # 1. 執行智能篩選
            opportunities = scanner.scan_funding_opportunities()
            
            if not opportunities:
                print("😴 目前市場平靜，無高報酬機會。")
            else:
                print(f"🔥 發現 {len(opportunities)} 個潛在機會，列出 TOP 5：")
                print("-" * 100) # 加長分隔線
                # 更新標題列：加入 價差 和 深度
                header = f"{'幣種':<12} {'年化':<8} {'價差%':<8} {'深度(U)':<10} {'策略 (做空/做多)':<35} {'穩定度'}"
                print(header)
                print("-" * 100)

                # 只顯示前 5 名
                for i, op in enumerate(opportunities[:5]):
                    short_info = f"Short {op['short_ex']} ({op['short_rate']*100:.4f}%)"
                    long_info = f"Long {op['long_ex']} ({op['long_rate']*100:.4f}%)"
                    strategy_str = f"{short_info} | {long_info}"
                    
                    # 格式化深度顯示 (例如 50000 -> 50k)
                    depth_str = f"{op['depth']/1000:.0f}k" if op['depth'] > 1000 else f"{op['depth']:.0f}"
                    
                    # 組合輸出
                    # op['spread_price'] 就是剛剛算的價差
                    print(f"{op['symbol']:<12} {op['apr']:>6.1f}%  {op['spread_price']:>6.2f}%  {depth_str:<10} {strategy_str:<35} {op['sigma']:>6.5f}")
            
            # 2. 執行資產安全劃轉
            guard.balance_security_transfer()
            
        except Exception as e:
            print(f"掃描異常: {e}")
        
        print("======================================\n")
        time.sleep(60) # 每分鐘掃描一次

if __name__ == "__main__":
    print("🚀 量化套利系統 (Binance/Bybit/OKX) 全面啟動...")
    
    # 初始化模組
    my_scanner = SmartMarketScanner()
    my_guard = DynamicRiskGuard()

    # 啟動雙線程 (多工處理)
    # 線程 1: 風控 (Daemon=True 代表主程式關閉時它也會關閉)
    t_monitor = threading.Thread(target=run_risk_monitor, args=(my_guard,), daemon=True)
    
    # 線程 2: 掃描
    t_scan = threading.Thread(target=run_market_scan, args=(my_scanner, my_guard,), daemon=True)

    t_monitor.start()
    t_scan.start()

    # 主程式保持運行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 系統安全關閉")