import time
from dataclasses import dataclass

@dataclass
class AccountState:
    name: str
    balance: float       # 錢包餘額
    unrealized_pnl: float # 未實現盈虧
    used_margin: float    # 已用保證金
    
    @property
    def equity(self):
        return self.balance + self.unrealized_pnl
    
    @property
    def margin_level(self):
        """風險率: 越小越安全，越大越危險 (>80% 危險)"""
        if self.equity <= 0: return 999
        return self.used_margin / self.equity

class DynamicRiskGuard:
    def __init__(self):
        # 模擬連接交易所帳戶
        # 實戰中這裡會換成 ccxt.fetch_balance() 和 fetch_positions()
        self.accounts = {
            'binance': AccountState('Binance', 10000, 500, 3000), # 賺錢中
            'bybit':   AccountState('Bybit', 10000, -200, 3000),  # 小虧
            'okx':     AccountState('OKX', 10000, -4000, 3000)    # 大虧 (危險!)
        }
        print("🛡️ 動態風控系統啟動：5秒級監控中...")

    def update_states(self):
        """
        [任務2] 5秒級監控：更新所有帳戶水位
        這裡模擬從 API 獲取最新數據
        """
        # (此處省略 API 呼叫，直接使用 self.accounts 進行模擬運算)
        pass

    def check_margin_health(self):
        """
        [任務2] 自動執行跨平台資金對沖
        """
        alert_triggered = False
        for name, acc in self.accounts.items():
            # 監控日誌
            status = "✅"
            if acc.margin_level > 0.8: status = "🔥 危險"
            elif acc.margin_level > 0.6: status = "⚠️ 警告"
            
            print(f"[{name}] 權益: ${acc.equity:.0f} | 風險率: {acc.margin_level*100:.1f}% {status}")
            
            # 風控邏輯：如果風險率 > 80%，強制減倉
            if acc.margin_level > 0.8:
                print(f"🚨 警報：{name} 水位過低！正在執行自動對沖減倉...")
                self.execute_deleveraging(name)
                alert_triggered = True
        return alert_triggered

    def execute_deleveraging(self, risky_exchange):
        """
        執行雙邊減倉：危險那邊平倉止損，賺錢那邊平倉止盈
        """
        # 這裡會呼叫 ccxt.create_order 進行平倉
        print(f"   >>> 已在 {risky_exchange} 市價平倉 20% 部位 (釋放保證金)")
        print(f"   >>> 已在 對沖端(Binance) 市價平倉 20% 部位 (鎖定獲利)")

    def balance_security_transfer(self):
        """
        [任務3] 安全保障：盈利撥款至風險倉位
        邏輯：計算各帳戶權益，如果偏差過大，建議/執行劃轉
        """
        equities = {k: v.equity for k, v in self.accounts.items()}
        avg_equity = sum(equities.values()) / len(equities)
        
        print("\n💰 [資產安全掃描] 正在檢查資金平衡...")
        
        for name, eq in equities.items():
            diff = eq - avg_equity
            # 如果某個帳戶錢太多 (超過平均 1000 U)，且另一個帳戶錢太少
            if diff > 1000: 
                print(f"   💎 {name} 盈利累積過多 (高於平均 ${diff:.0f})")
                print(f"   👉 系統自動撥款: 將 ${diff/2:.0f} 劃轉至低水位帳戶，確保極端行情安全。")
                # 實戰：呼叫 exchange.withdraw() 或內部劃轉 API

if __name__ == "__main__":
    guard = DynamicRiskGuard()
    guard.check_margin_health()
    guard.balance_security_transfer()