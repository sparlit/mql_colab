import MetaTrader5 as mt5
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

# Configure Streamlit Dashboard Layout
st.set_page_config(page_title="Forex MTF Command Center", layout="wide")
st.title("⚡ Institutional Multi-Timeframe Command Center")

# Define all 21 native MT5 timeframes mapped to their configuration tuples
TF_MAP = {
    "M1": (mt5.TIMEFRAME_M1, 60),    "M2": (mt5.TIMEFRAME_M2, 120),    "M3": (mt5.TIMEFRAME_M3, 180),
    "M4": (mt5.TIMEFRAME_M4, 240),   "M5": (mt5.TIMEFRAME_M5, 300),   "M6": (mt5.TIMEFRAME_M6, 360),
    "M10": (mt5.TIMEFRAME_M10, 600), "M12": (mt5.TIMEFRAME_M12, 720), "M15": (mt5.TIMEFRAME_M15, 900),
    "M20": (mt5.TIMEFRAME_M20, 1200),"M30": (mt5.TIMEFRAME_M30, 1800),"H1": (mt5.TIMEFRAME_H1, 3600),
    "H2": (mt5.TIMEFRAME_H2, 7200),  "H3": (mt5.TIMEFRAME_H3, 10800), "H4": (mt5.TIMEFRAME_H4, 14400),
    "H6": (mt5.TIMEFRAME_H6, 21600), "H8": (mt5.TIMEFRAME_H8, 28800), "H12": (mt5.TIMEFRAME_H12, 43200),
    "D1": (mt5.TIMEFRAME_D1, 86400), "W1": (mt5.TIMEFRAME_W1, 604800),"MN1": (mt5.TIMEFRAME_MN1, 2592000)
}

# Sidebar Dashboard Controls
st.sidebar.header("Data Pipeline Settings")
target_symbol = st.sidebar.text_input("Asset Symbol", value="EURUSD").upper()
candles_to_view = st.sidebar.slider("Candle Depth History", min_value=5, max_value=100, value=10)
selected_view_tf = st.sidebar.selectbox("Primary Timeframe View", list(TF_MAP.keys()), index=11) # Defaults to H1

# Initialize connection loop
if not mt5.initialize():
    st.error(f"Failed to bind connection to MT5 terminal core: {mt5.last_error()}")
    st.stop()

# Pull basic asset metrics
symbol_info = mt5.symbol_info(target_symbol)
tick_info = mt5.symbol_info_tick(target_symbol)

if symbol_info is None or tick_info is None:
    st.error(f"Symbol '{target_symbol}' not found or no tick data available. Verify market watch window.")
    mt5.shutdown()
    st.stop()

# Global Clock Synchronization
broker_time = datetime.fromtimestamp(tick_info.time)

# Layout KPI summary metrics bar
col1, col2, col3, col4 = st.columns(4)
col1.metric("Asset", target_symbol)
col2.metric("Live Bid Price", f"{tick_info.bid:.5f}")
col3.metric("Live Ask Price", f"{tick_info.ask:.5f}")
col4.metric("Broker Time Clock", broker_time.strftime('%H:%M:%S'))

st.markdown("---")

# Pipeline Core Extraction Logic
def get_processed_dataframe(symbol, tf_str, length, current_clock):
    tf_constant, tf_seconds = TF_MAP[tf_str]
    rates = mt5.copy_rates_from_pos(symbol, tf_constant, 0, length)
    
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
        
    df = pd.DataFrame(rates)
    df['Open Time'] = pd.to_datetime(df['time'], unit='s')
    df['Expected Close'] = df['Open Time'] + pd.to_timedelta(tf_seconds, unit='s')
    
    # Calculate countdown metrics for the active candle
    live_candle_close = df.loc[df.index[-1], 'Expected Close']
    time_left = live_candle_close - current_clock
    
    df['Countdown'] = "Closed Session"
    if time_left.total_seconds() > 0:
        df.loc[df.index[-1], 'Countdown'] = str(timedelta(seconds=int(time_left.total_seconds())))
    else:
        df.loc[df.index[-1], 'Countdown'] = "Awaiting Tick"
        
    df = df[['Open Time', 'Expected Close', 'Countdown', 'open', 'high', 'low', 'close', 'tick_volume']]
    df.columns = ['Open Time', 'Expected Close', 'Countdown', 'Open', 'High', 'Low', 'Close', 'Tick Vol']
    return df

# Main Dashboard Interface Tabs
tab_primary, tab_matrix = st.tabs(["🎯 Primary Focus Window", "📊 All-Timeframe Overview Matrix"])

with tab_primary:
    st.subheader(f"Detailed View: {target_symbol} {selected_view_tf}")
    primary_df = get_processed_dataframe(target_symbol, selected_view_tf, candles_to_view, broker_time)
    
    if not primary_df.empty:
        # Display the live candle countdown prominently
        current_candle_countdown = primary_df.iloc[-1]['Countdown']
        st.info(f"⏳ Live Candle Remaining Time for {selected_view_tf}: **{current_candle_countdown}**")
        st.dataframe(primary_df.sort_values(by='Open Time', ascending=False), use_container_width=True)
    else:
        st.warning("No data retrieved for the selected timeframe configuration.")

with tab_matrix:
    st.subheader("Simultaneous Multi-Timeframe Core State Grid")
    st.write("Displays the real-time status of the current active candle across various timeframes.")
    
    summary_matrix_rows = []
    
    for tf_label in TF_MAP.keys():
        quick_df = get_processed_dataframe(target_symbol, tf_label, 1, broker_time)
        if not quick_df.empty:
            live_row = quick_df.iloc[-1]
            summary_matrix_rows.append({
                "Timeframe": tf_label,
                "Candle Open Clock": live_row['Open Time'].strftime('%Y-%m-%d %H:%M:%S'),
                "Time Remaining": live_row['Countdown'],
                "Open Price": live_row['Open'],
                "High Price": live_row['High'],
                "Low Price": live_row['Low'],
                "Current/Close": live_row['Close'],
                "Tick Counter": live_row['Tick Vol']
            })
            
    summary_matrix_df = pd.DataFrame(summary_matrix_rows)
    st.dataframe(summary_matrix_df, use_container_width=True, hide_index=True)

mt5.shutdown()

# Auto-refresh mechanism built natively into Streamlit layout
st.button("🔄 Force Refresh Matrix Pipeline")
