import streamlit as st
import pandas as pd
import numpy as np
import time
import os
from datetime import datetime
import plotly.graph_objects as go
from dotenv import load_dotenv

# 導入自定義模組
from market_scanner import SmartMarketScanner
from risk_guard import DynamicRiskGuard

# 載入環境變數
load_dotenv()

# 頁面配置
st.set_page_config(
    page_title="Crypto Arbitrage Dashboard",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 自定義 CSS 強化黑夜模式視覺效果
st.markdown("""
    <style>
    .main {
        background-color: #0e1117;
    }
    .stMetric {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #30363d;
    }
    .stDataFrame {
        border: 1px solid #30363d;
    }
    </style>
    """, unsafe_allow_html=True)

# 初始化 Session State
if 'scanner' not in st.session_state:
    st.session_state.scanner = None
if 'guard' not in st.session_state:
    st.session_state.guard = None
if 'last_update' not in st.session_state:
    st.session_state.last_update = "從未更新"

# 側邊欄控制
st.sidebar.title("⚙️ 系統控制")
use_mock = st.sidebar.checkbox("使用模擬數據 (Mock Data)", value=True)
refresh_rate = st.sidebar.slider("自動刷新頻率 (秒)", 5, 300, 60)

if st.sidebar.button("立即手動刷新"):
    st.rerun()

# 初始化或更新實例
if st.session_state.scanner is None or st.session_state.scanner.use_mock != use_mock:
    st.session_state.scanner = SmartMarketScanner(use_mock=use_mock)
    st.session_state.guard = DynamicRiskGuard(use_mock=use_mock)

# 獲取數據
with st.spinner('正在獲取市場數據...'):
    st.session_state.guard.update_states()
    opportunities = st.session_state.scanner.scan_funding_opportunities()
    st.session_state.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 主界面標題
st.title("🚀 Crypto Arbitrage 智能監控系統")
st.caption(f"最後更新時間: {st.session_state.last_update} | 模式: {'模擬' if use_mock else '實戰'}")

# 第一排：風險儀表板 (Risk Gauges)
st.subheader("🛡️ 帳戶風險監控")
cols = st.columns(len(st.session_state.guard.accounts))

for i, (name, acc) in enumerate(st.session_state.guard.accounts.items()):
    with cols[i]:
        # 計算風險顏色
        color = "green"
        if acc.margin_level > 0.8: color = "red"
        elif acc.margin_level > 0.6: color = "orange"
        
        # 使用 Plotly 繪製儀表盤
        fig = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = acc.margin_level * 100,
            domain = {'x': [0, 1], 'y': [0, 1]},
            title = {'text': f"{name} 風險率 (%)", 'font': {'size': 18}},
            gauge = {
                'axis': {'range': [None, 100], 'tickwidth': 1, 'tickcolor': "white"},
                'bar': {'color': color},
                'bgcolor': "rgba(0,0,0,0)",
                'borderwidth': 2,
                'bordercolor': "#30363d",
                'steps': [
                    {'range': [0, 60], 'color': 'rgba(0, 255, 0, 0.1)'},
                    {'range': [60, 80], 'color': 'rgba(255, 165, 0, 0.1)'},
                    {'range': [80, 100], 'color': 'rgba(255, 0, 0, 0.1)'}
                ],
                'threshold': {
                    'line': {'color': "red", 'width': 4},
                    'thickness': 0.75,
                    'value': 80
                }
            }
        ))
        fig.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor='rgba(0,0,0,0)', font={'color': "white"})
        st.plotly_chart(fig, use_container_width=True)
        
        # 顯示詳細指標
        m1, m2 = st.columns(2)
        m1.metric("權益 (Equity)", f"${acc.equity:,.0f}")
        m2.metric("未實現盈虧", f"${acc.unrealized_pnl:,.0f}", delta=f"{acc.unrealized_pnl:,.0f}")

# 第二排：套利機會表格
st.subheader("🔥 最佳資金費率套利機會")

if not opportunities:
    st.info("😴 目前市場平靜，無高報酬機會。")
else:
    # 轉換為 DataFrame 進行顯示
    df = pd.DataFrame(opportunities)
    
    # 格式化顯示
    display_df = pd.DataFrame({
        '幣種': df['symbol'],
        '預估年化 (APR)': df['apr'].map('{:.2f}%'.format),
        '價差 (Spread %)': df['spread_price'].map('{:.3f}%'.format),
        '深度 (Depth U)': df['depth'].apply(lambda x: f"{x/1000:.1f}k" if x > 1000 else f"{x:.0f}"),
        '做空交易所': df['short_ex'].str.upper(),
        '做多交易所': df['long_ex'].str.upper(),
        '穩定度 (σ)': df['sigma'].map('{:.5f}'.format)
    })
    
    # 使用 st.dataframe 並自定義樣式
    def color_spread(val):
        val_float = float(val.replace('%', ''))
        color = 'red' if val_float > 0 else 'green'
        return f'color: {color}'

    st.dataframe(
        display_df.style.applymap(color_spread, subset=['價差 (Spread %)']),
        use_container_width=True,
        height=400
    )

# 第三排：資產安全與回測
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("💰 資產安全掃描")
    logs = st.session_state.guard.balance_security_transfer()
    if not logs:
        st.success("✅ 資金分佈均勻，無需劃轉。")
    else:
        for log in logs:
            st.warning(log)

with col_right:
    st.subheader("📊 策略回測 (Top 1)")
    if opportunities:
        top_symbol = opportunities[0]['symbol']
        roi, mdd = st.session_state.scanner.backtest_strategy(top_symbol)
        
        st.write(f"針對 **{top_symbol}** 的 30 天模擬回測：")
        c1, c2 = st.columns(2)
        c1.metric("預估 ROI", f"{roi:.2f}%")
        c2.metric("最大回撤 (MDD)", f"{mdd:.2f}%")
        
        # 繪製簡單的 PnL 曲線 (模擬)
        chart_data = pd.DataFrame(
            np.random.randn(30, 1).cumsum() + 100,
            columns=['PnL Trend']
        )
        st.line_chart(chart_data)

# 自動刷新邏輯
if refresh_rate > 0:
    time.sleep(refresh_rate)
    st.rerun()
