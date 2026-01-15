import streamlit as st
import pandas as pd
import time
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import load_dotenv
import threading

from market_scanner_v2 import SmartMarketScanner
from risk_guard_v2 import DynamicRiskGuard

# 加載環境變量
load_dotenv()

# 頁面配置
st.set_page_config(
    page_title="Crypto Arbitrage Pro V2",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定義 CSS
st.markdown("""
<style>
    .stMetric {
        background-color: #0e1117;
        padding: 10px;
        border-radius: 5px;
    }
    .profit-text {
        color: #00ff00;
        font-weight: bold;
    }
    .loss-text {
        color: #ff4b4b;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# 初始化狀態
if 'scanner' not in st.session_state:
    st.session_state.scanner = None
if 'guard' not in st.session_state:
    st.session_state.guard = None
if 'last_update' not in st.session_state:
    st.session_state.last_update = None
if 'auto_refresh' not in st.session_state:
    st.session_state.auto_refresh = False

# ========== 側邊欄 ==========
st.sidebar.title("⚡ 控制台")

# 模式選擇
use_mock = st.sidebar.checkbox("🧪 使用模擬數據", value=False, help="使用模擬數據進行測試")

# 刷新設置
st.sidebar.subheader("🔄 刷新設置")
auto_refresh = st.sidebar.checkbox("自動刷新", value=False, help="每60秒自動更新數據")
st.session_state.auto_refresh = auto_refresh

if st.sidebar.button("🔄 立即刷新", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

# 風險閾值設置
st.sidebar.subheader("⚙️ 風控參數")
danger_threshold = st.sidebar.slider("警告閾值", 50, 90, 80, help="保證金使用率警告線")
critical_threshold = st.sidebar.slider("危險閾值", 60, 95, 90, help="保證金使用率危險線")

st.sidebar.divider()

# 篩選設置
st.sidebar.subheader("🎯 機會篩選")
min_apr = st.sidebar.number_input("最低 APR (%)", 0.0, 100.0, 10.0, 1.0)
max_breakeven = st.sidebar.number_input("最大回本天數", 0.5, 30.0, 5.0, 0.5)
min_depth = st.sidebar.number_input("最小深度 (USD)", 0, 10000000, 500000, 100000)

# ========== 初始化系統 ==========
if st.session_state.scanner is None or st.session_state.scanner.use_mock != use_mock:
    with st.spinner('🚀 初始化交易系統...'):
        st.session_state.scanner = SmartMarketScanner(use_mock=use_mock)
        st.session_state.guard = DynamicRiskGuard(use_mock=use_mock)
        st.session_state.guard.DANGER_MARGIN_LEVEL = danger_threshold / 100
        st.session_state.guard.CRITICAL_MARGIN_LEVEL = critical_threshold / 100

# ========== 獲取市場數據 ==========
@st.cache_data(ttl=60, show_spinner=False)
def get_market_data(_scanner, _timestamp):
    """緩存市場數據（60秒）"""
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    def progress_callback(completed, total):
        progress = completed / total
        progress_bar.progress(progress)
        status_text.text(f"掃描進度: {completed}/{total} ({progress*100:.0f}%)")
    
    opportunities = _scanner.scan_funding_opportunities(progress_callback)
    
    progress_bar.empty()
    status_text.empty()
    
    return opportunities

# 獲取數據
with st.spinner('🔍 分析市場機會...'):
    current_time = datetime.now()
    opportunities = get_market_data(
        st.session_state.scanner,
        current_time.strftime("%Y-%m-%d %H:%M")
    )
    
    # 更新風控
    st.session_state.guard.update_states()
    positions_df = st.session_state.guard.get_positions_df()
    summary_stats = st.session_state.guard.get_summary_stats()
    
    st.session_state.last_update = current_time

# ========== 頁面標題 ==========
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    st.title("⚡ Crypto Arbitrage 智能監控 V2")

with col2:
    mode_label = "🧪 模擬" if use_mock else "🔴 實戰"
    st.metric("模式", mode_label)

with col3:
    if st.session_state.last_update:
        update_time = st.session_state.last_update.strftime("%H:%M:%S")
        st.metric("更新時間", update_time)

st.divider()

# ========== 總覽儀表板 ==========
st.subheader("📊 資產總覽")

overview_cols = st.columns(4)

with overview_cols[0]:
    total_equity = summary_stats['total_equity']
    st.metric(
        "總權益",
        f"${total_equity:,.2f}",
        help="所有帳戶權益總和"
    )

with overview_cols[1]:
    total_pnl = summary_stats['total_pnl']
    pnl_color = "normal" if total_pnl >= 0 else "inverse"
    st.metric(
        "總未實現損益",
        f"${total_pnl:,.2f}",
        f"{(total_pnl/total_equity*100) if total_equity > 0 else 0:.2f}%",
        delta_color=pnl_color
    )

with overview_cols[2]:
    avg_margin = summary_stats['avg_margin_level'] * 100
    st.metric(
        "平均保證金率",
        f"{avg_margin:.1f}%",
        help="所有帳戶平均保證金使用率"
    )

with overview_cols[3]:
    total_positions = summary_stats['total_positions']
    st.metric(
        "持倉數量",
        total_positions,
        help="當前活躍持倉總數"
    )

st.divider()

# ========== 帳戶風險監控 ==========
st.subheader("🛡️ 帳戶風險監控")

risk_cols = st.columns(3)
accounts = ['binance', 'bybit', 'okx']

for i, account_name in enumerate(accounts):
    with risk_cols[i]:
        account = st.session_state.guard.accounts[account_name]
        
        # 保證金儀表盤
        margin_pct = account.margin_level * 100
        
        # 顏色邏輯
        if margin_pct < 50:
            color = "green"
        elif margin_pct < 70:
            color = "yellow"
        elif margin_pct < 85:
            color = "orange"
        else:
            color = "red"
        
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=margin_pct,
            title={'text': f"{account_name.upper()}<br>{account.risk_score}", 'font': {'size': 16}},
            delta={'reference': 50, 'increasing': {'color': "red"}, 'decreasing': {'color': "green"}},
            gauge={
                'axis': {'range': [None, 100], 'tickwidth': 1},
                'bar': {'color': color},
                'steps': [
                    {'range': [0, 30], 'color': "rgba(0, 255, 0, 0.1)"},
                    {'range': [30, 50], 'color': "rgba(255, 255, 0, 0.1)"},
                    {'range': [50, 70], 'color': "rgba(255, 165, 0, 0.1)"},
                    {'range': [70, 100], 'color': "rgba(255, 0, 0, 0.1)"}
                ],
                'threshold': {
                    'line': {'color': "white", 'width': 4},
                    'thickness': 0.75,
                    'value': danger_threshold
                }
            }
        ))
        
        fig.update_layout(
            height=200,
            margin=dict(l=20, r=20, t=50, b=20),
            paper_bgcolor="rgba(0,0,0,0)",
            font={'color': "white"}
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # 詳細信息
        metric_cols = st.columns(2)
        with metric_cols[0]:
            st.metric("權益", f"${account.equity:,.0f}")
            st.metric("已用保證金", f"${account.used_margin:,.0f}")
        
        with metric_cols[1]:
            pnl_delta = "normal" if account.unrealized_pnl >= 0 else "inverse"
            st.metric("未實現損益", f"${account.unrealized_pnl:,.2f}", delta_color=pnl_delta)
            st.metric("持倉數", f"{account.total_positions}")

st.divider()

# ========== 當前持倉 ==========
st.subheader("💼 當前持倉詳情")

if not positions_df.empty:
    # 自定義樣式函數
    def color_pnl(val):
        try:
            if isinstance(val, str):
                val = float(val.replace('$', '').replace(',', ''))
            if val > 0:
                return 'color: #00ff00; font-weight: bold'
            elif val < 0:
                return 'color: #ff4b4b; font-weight: bold'
        except:
            pass
        return ''
    
    def color_roi(val):
        try:
            if val > 0:
                return 'background-color: rgba(0, 255, 0, 0.2); color: #00ff00; font-weight: bold'
            elif val < 0:
                return 'background-color: rgba(255, 75, 75, 0.2); color: #ff4b4b; font-weight: bold'
        except:
            pass
        return ''
    
    styled_df = positions_df.style \
        .map(color_pnl, subset=['未實現損益']) \
        .map(color_pnl, subset=['盈虧%']) \
        .map(color_roi, subset=['ROI']) \
        .format({
            '盈虧%': '{:.3f}%',
            '未實現損益': '${:,.2f}',
            'ROI': '{:+.2f}%'
        })
    
    st.dataframe(styled_df, use_container_width=True, height=400)
    
    # 持倉統計
    pos_stats_cols = st.columns(4)
    
    with pos_stats_cols[0]:
        total_margin = positions_df['保證金'].str.replace('$', '').str.replace(',', '').astype(float).sum()
        st.metric("總保證金", f"${total_margin:,.2f}")
    
    with pos_stats_cols[1]:
        total_pnl_pos = summary_stats['total_pnl']
        st.metric("總損益", f"${total_pnl_pos:,.2f}")
    
    with pos_stats_cols[2]:
        avg_holding = positions_df['持倉時間'].str.replace('h', '').astype(float).mean()
        st.metric("平均持倉", f"{avg_holding:.1f}h")
    
    with pos_stats_cols[3]:
        total_fees = positions_df['已付手續費'].str.replace('$', '').str.replace(',', '').astype(float).sum()
        st.metric("已付手續費", f"${total_fees:.2f}")
else:
    st.info("📭 當前無持倉")

st.divider()

# ========== 套利機會列表 ==========
st.subheader("🔥 最佳資金費率機會")

if opportunities:
    # 篩選
    filtered_opps = [
        opp for opp in opportunities
        if opp['apr'] >= min_apr
        and opp['breakeven_days'] <= max_breakeven
        and opp['depth'] >= min_depth
    ]
    
    if filtered_opps:
        df = pd.DataFrame(filtered_opps)
        
        display_df = pd.DataFrame({
            '幣種': df['symbol'],
            '做多': df['long_ex'].str.upper(),
            '做空': df['short_ex'].str.upper(),
            '買入價': df['long_price'].map('${:,.2f}'.format),
            '賣出價': df['short_price'].map('${:,.2f}'.format),
            '當期費率': (df['rate_diff'] * 100).map('{:.4f}%'.format),
            '年化收益': df['apr'].map('{:.2f}%'.format),
            '價差成本': df['spread'].map('{:.3f}%'.format),
            '手續費': df['fees'].map('{:.3f}%'.format),
            '總成本': df['total_cost'].map('{:.3f}%'.format),
            '回本天數': df['breakeven_days'].apply(
                lambda x: "⚡ 立即盈利" if x <= 0 else (
                    f"🟢 {x:.1f}天" if x <= 3 else (
                        f"🟡 {x:.1f}天" if x <= 7 else f"🟠 {x:.1f}天"
                    )
                )
            ),
            '深度': df['depth'].apply(lambda x: f"${x/1000000:.2f}M" if x >= 1000000 else f"${x/1000:.0f}K"),
            '波動率': df['sigma'].map('{:.4f}'.format)
        })
        
        # 樣式
        def highlight_breakeven(val):
            if "立即" in val or "⚡" in val:
                return 'background-color: rgba(0, 255, 0, 0.3); color: #00ff00; font-weight: bold'
            if "🟢" in val:
                return 'background-color: rgba(0, 255, 0, 0.2); color: #00ff00'
            if "🟡" in val:
                return 'background-color: rgba(255, 255, 0, 0.2); color: #ffff00'
            return ''
        
        def highlight_apr(val):
            try:
                apr = float(val.strip('%'))
                if apr >= 30:
                    return 'background-color: rgba(0, 255, 0, 0.3); color: #00ff00; font-weight: bold'
                if apr >= 20:
                    return 'background-color: rgba(0, 255, 0, 0.2); color: #00ff00'
                if apr >= 10:
                    return 'color: #00ff00'
            except:
                pass
            return ''
        
        def highlight_cost(val):
            try:
                cost = float(val.strip('%'))
                if cost <= 0:
                    return 'color: #00ff00; font-weight: bold'
                if cost <= 0.1:
                    return 'color: #00ff00'
            except:
                pass
            return ''
        
        styled_opportunities = display_df.style \
            .map(highlight_breakeven, subset=['回本天數']) \
            .map(highlight_apr, subset=['年化收益']) \
            .map(highlight_cost, subset=['總成本'])
        
        st.dataframe(styled_opportunities, use_container_width=True, height=600)
        
        # 機會統計
        opp_stats_cols = st.columns(4)
        
        with opp_stats_cols[0]:
            st.metric("優質機會", len(filtered_opps), f"/{len(opportunities)}")
        
        with opp_stats_cols[1]:
            avg_apr = df['apr'].mean()
            st.metric("平均 APR", f"{avg_apr:.2f}%")
        
        with opp_stats_cols[2]:
            avg_breakeven = df['breakeven_days'].mean()
            st.metric("平均回本", f"{avg_breakeven:.1f}天")
        
        with opp_stats_cols[3]:
            total_depth = df['depth'].sum()
            st.metric("總深度", f"${total_depth/1000000:.1f}M")
    else:
        st.warning(f"⚠️ 無符合條件的機會（APR≥{min_apr}%, 回本≤{max_breakeven}天, 深度≥${min_depth/1000:.0f}K）")
else:
    st.warning("📉 當前無高收益機會")

st.divider()

# ========== 風險警告 ==========
warnings = st.session_state.guard.check_risks()
if warnings:
    st.subheader("⚠️ 風險警告")
    for warning in warnings:
        st.warning(warning)

# ========== 自動刷新 ==========
if st.session_state.auto_refresh:
    time.sleep(60)
    st.rerun()
