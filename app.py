import streamlit as st
import pandas as pd
from datetime import datetime
from market_scanner import SmartMarketScanner

# 頁面配置
st.set_page_config(
    page_title="Crypto Arbitrage",
    page_icon="⚡",
    layout="wide"
)

# 初始化
if 'scanner' not in st.session_state:
    st.session_state.scanner = None
if 'last_update' not in st.session_state:
    st.session_state.last_update = None

# 側邊欄
st.sidebar.title("⚡ 控制台")
use_mock = st.sidebar.checkbox("🧪 使用模擬數據", value=False)

if st.sidebar.button("🔄 刷新", use_container_width=True):
    st.cache_data.clear()
    st.session_state.scanner = None
    st.rerun()

# 初始化掃描器
if st.session_state.scanner is None:
    with st.spinner('初始化...'):
        st.session_state.scanner = SmartMarketScanner(use_mock=use_mock)

# 獲取數據
@st.cache_data(ttl=60, show_spinner=False)
def get_market_data(_scanner, _timestamp):
    return _scanner.scan_funding_opportunities()

with st.spinner('🔍 掃描市場...'):
    current_time = datetime.now()
    opportunities = get_market_data(
        st.session_state.scanner,
        current_time.strftime("%Y-%m-%d %H:%M")
    )
    st.session_state.last_update = current_time

# 頁面標題
col1, col2 = st.columns([3, 1])
with col1:
    st.title("⚡ 資金費率套利監控")
with col2:
    if st.session_state.last_update:
        st.metric("更新", st.session_state.last_update.strftime("%H:%M:%S"))

st.divider()

# 顯示機會
st.subheader("🔥 資金費率機會")

if opportunities:
    df = pd.DataFrame(opportunities)
    
    # 格式化顯示
    display_df = pd.DataFrame({
        '幣種': df['symbol'],
        '做多': df['long_ex'].str.upper(),
        '做空': df['short_ex'].str.upper(),
        '買入價': df['long_price'].map('${:,.2f}'.format),
        '賣出價': df['short_price'].map('${:,.2f}'.format),
        '結算': df['funding_interval'].apply(lambda x: f"{x}h/{int(24/x)}次"),
        '費率差': (df['rate_diff'] * 100).map('{:.4f}%'.format),
        'APR': df['apr'].map('{:.2f}%'.format),
        '價差': df['spread'].map('{:.3f}%'.format),
        '手續費': df['fees'].map('{:.3f}%'.format),
        '總成本': df['total_cost'].map('{:.3f}%'.format),
        '回本': df['breakeven_days'].apply(
            lambda x: "⚡" if x <= 0 else f"{x:.1f}天"
        ),
        '深度': df['depth'].apply(
            lambda x: f"${x/1000000:.2f}M" if x >= 1000000 else f"${x/1000:.0f}K"
        )
    })
    
    st.dataframe(display_df, use_container_width=True, height=600)
    
    # 統計
    st.divider()
    cols = st.columns(4)
    with cols[0]:
        st.metric("總機會", len(opportunities))
    with cols[1]:
        st.metric("平均 APR", f"{df['apr'].mean():.2f}%")
    with cols[2]:
        st.metric("平均回本", f"{df['breakeven_days'].mean():.1f}天")
    with cols[3]:
        st.metric("總深度", f"${df['depth'].sum()/1000000:.1f}M")
else:
    st.warning("📉 當前無機會")
    st.info("請確保網絡連接正常，或點擊「刷新」重試")
