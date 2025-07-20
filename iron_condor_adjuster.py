import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objs as go
import os
import json

st.set_page_config(page_title="Iron Condor Adjuster", layout="wide")
st.title("🧵 Iron Condor Setup & Auto Adjuster")

LOCK_FILE = "locked_iron_condor.json"
LOT_SIZE = 75

# --- Helper Functions ---

def detect_atm(df):
    df['Call Delta'] = pd.to_numeric(df['Call Delta'], errors='coerce')
    df['Delta Diff'] = abs(df['Call Delta'] - 0.5)
    return int(round(df.sort_values('Delta Diff').iloc[0]['Strike'], -2))

def suggest_initial_legs(df, atm):
    ce = df[(df['Strike'] > atm) & (df['Call LTP'].between(90, 110))].sort_values('Strike')
    pe = df[(df['Strike'] < atm) & (df['Put LTP'].between(90, 110))].sort_values('Strike', ascending=False)

    if ce.empty or pe.empty:
        return None

    sell_ce = ce.iloc[0]
    sell_ce_strike = sell_ce['Strike']
    sell_ce_premium = sell_ce['Call LTP']

    ce_buy_candidates = df[(df['Strike'] > sell_ce_strike) & (df['Call LTP'] < sell_ce_premium / 2)].copy()
    ce_buy_candidates['Premium_Diff'] = abs(ce_buy_candidates['Call LTP'] - (sell_ce_premium / 3))
    buy_ce = ce_buy_candidates.sort_values('Premium_Diff').iloc[0]

    sell_pe = pe.iloc[0]
    sell_pe_strike = sell_pe['Strike']
    sell_pe_premium = sell_pe['Put LTP']

    pe_buy_candidates = df[(df['Strike'] < sell_pe_strike) & (df['Put LTP'] < sell_pe_premium / 2)].copy()
    pe_buy_candidates['Premium_Diff'] = abs(pe_buy_candidates['Put LTP'] - (sell_pe_premium / 3))
    buy_pe = pe_buy_candidates.sort_values('Premium_Diff').iloc[0]

    return pd.DataFrame([
        {'Leg': 'Sell PE', 'Strike': sell_pe_strike, 'Premium': sell_pe_premium},
        {'Leg': 'Buy PE', 'Strike': buy_pe['Strike'], 'Premium': buy_pe['Put LTP']},
        {'Leg': 'Sell CE', 'Strike': sell_ce_strike, 'Premium': sell_ce_premium},
        {'Leg': 'Buy CE', 'Strike': buy_ce['Strike'], 'Premium': buy_ce['Call LTP']},
    ])

def calculate_payoff(legs):
    spot_range = np.arange(legs['Strike'].min() - 200, legs['Strike'].max() + 200, 10)
    payoffs = []
    for spot in spot_range:
        payoff = 0
        for _, row in legs.iterrows():
            intrinsic = max(row['Strike'] - spot, 0) if 'PE' in row['Leg'] else max(spot - row['Strike'], 0)
            payoff += (row['Premium'] - intrinsic) if 'Sell' in row['Leg'] else (intrinsic - row['Premium'])
        payoffs.append(payoff * LOT_SIZE)
    return pd.DataFrame({'Spot Price': spot_range, 'Payoff': payoffs})

def check_adjustments(old, current, drop_threshold=0.5):
    messages = []
    for _, row in old.iterrows():
        match = current[(current['Leg'] == row['Leg']) & (current['Strike'] == row['Strike'])]
        if not match.empty:
            new_premium = match.iloc[0]['Premium']
            change = new_premium - row['Premium']
            if 'Sell' in row['Leg'] and change < 0 and abs(change) > row['Premium'] * drop_threshold:
                messages.append((row['Leg'], row['Strike']))
    return messages

def suggest_new_leg(df, leg, atm):
    if 'PE' in leg:
        side = 'Put LTP'
        filtered = df[(df[side].between(90, 110)) & (df['Strike'] < atm)].sort_values('Strike', ascending=False)
    else:
        side = 'Call LTP'
        filtered = df[(df[side].between(90, 110)) & (df['Strike'] > atm)].sort_values('Strike')

    if filtered.empty:
        return None, None

    sell_leg = filtered.iloc[0]
    sell_strike = sell_leg['Strike']
    sell_premium = sell_leg[side]

    if 'PE' in leg:
        hedge_candidates = df[(df['Strike'] < sell_strike) & (df['Put LTP'] < sell_premium / 2)].copy()
        hedge_candidates['Premium_Diff'] = abs(hedge_candidates['Put LTP'] - (sell_premium / 3))
        if hedge_candidates.empty:
            return None, None
        hedge_leg = hedge_candidates.sort_values('Premium_Diff').iloc[0]
        hedge_ltp = hedge_leg['Put LTP']
    else:
        hedge_candidates = df[(df['Strike'] > sell_strike) & (df['Call LTP'] < sell_premium / 2)].copy()
        hedge_candidates['Premium_Diff'] = abs(hedge_candidates['Call LTP'] - (sell_premium / 3))
        if hedge_candidates.empty:
            return None, None
        hedge_leg = hedge_candidates.sort_values('Premium_Diff').iloc[0]
        hedge_ltp = hedge_leg['Call LTP']

    return (
        {'Leg': leg, 'Strike': sell_strike, 'Premium': sell_premium},
        {'Leg': 'Buy ' + leg.split()[-1], 'Strike': hedge_leg['Strike'], 'Premium': hedge_ltp}
    )

# --- Streamlit App Logic ---

uploaded = st.file_uploader("📄 Upload Sensibull Option Chain (CSV)", type=["csv"])

if uploaded:
    df = pd.read_csv(uploaded)
    df.columns = df.columns.str.strip()
    df['Strike'] = pd.to_numeric(df['Strike'], errors='coerce')
    df['Call LTP'] = pd.to_numeric(df['Call LTP'], errors='coerce')
    df['Put LTP'] = pd.to_numeric(df['Put LTP'], errors='coerce')

    atm = detect_atm(df)
    st.info(f"🎯 ATM Detected: {atm}")

    suggested = suggest_initial_legs(df, atm)
    if suggested is not None:
        st.subheader("📋 Suggested Iron Condor")
        st.dataframe(suggested)

        fig = go.Figure()
        payoff_df = calculate_payoff(suggested)
        fig.add_trace(go.Scatter(x=payoff_df['Spot Price'], y=payoff_df['Payoff'], mode='lines', name='Payoff'))
        fig.update_layout(title="📈 Iron Condor Payoff Chart", xaxis_title="Spot Price", yaxis_title="Profit / Loss", template="plotly_white", height=400)
        st.plotly_chart(fig, use_container_width=True)

        if not os.path.exists(LOCK_FILE):
            if st.button("🔒 Lock This Setup"):
                with open(LOCK_FILE, "w") as f:
                    json.dump(suggested.to_dict(orient="records"), f)
                st.success("✅ Setup locked.")
        else:
            with open(LOCK_FILE, "r") as f:
                locked_df = pd.DataFrame(json.load(f))

            st.subheader("📊 Locked Setup vs Today")

            live_data = []
            for _, row in locked_df.iterrows():
                leg = row['Leg']
                strike = row['Strike']
                premium_now = df[df['Strike'] == strike]['Put LTP'].values if 'PE' in leg else df[df['Strike'] == strike]['Call LTP'].values
                premium_now = premium_now[0] if len(premium_now) > 0 else np.nan
                live_data.append({
                    'Leg': leg,
                    'Strike': strike,
                    'Premium_locked': row['Premium'],
                    'Premium_now': premium_now
                })

            merged = pd.DataFrame(live_data)
            merged['∆ Premium'] = merged['Premium_now'] - merged['Premium_locked']

            st.dataframe(merged[['Leg', 'Strike', 'Premium_locked', 'Premium_now', '∆ Premium']])

            live_df = pd.DataFrame([
                {'Leg': row['Leg'], 'Strike': row['Strike'], 'Premium': row['Premium_now']}
                for _, row in merged.iterrows()
            ])
            to_adjust = check_adjustments(locked_df, live_df)

            if to_adjust:
                st.warning("⚠️ Adjustments Needed:")
                for leg, strike in to_adjust:
                    st.write(f"🔁 {leg} @ {strike} → Premium deviation exceeded threshold.")

                st.subheader("⚙️ Auto-Suggested Adjustment")
                new_legs = []
                for leg, _ in to_adjust:
                    sell, buy = suggest_new_leg(df, leg, atm)
                    if sell and buy:
                        new_legs.extend([sell, buy])
                if new_legs:
                    new_df = pd.DataFrame(new_legs)
                    st.dataframe(new_df)

                    new_fig = go.Figure()
                    new_po = calculate_payoff(new_df)
                    new_fig.add_trace(go.Scatter(x=new_po['Spot Price'], y=new_po['Payoff'], name='Adjusted'))
                    new_fig.update_layout(title="🔁 Adjusted Payoff", xaxis_title="Spot", yaxis_title="P/L")
                    st.plotly_chart(new_fig)
            else:
                st.success("✅ No adjustment needed.")

            if st.button("🔁 Reset Locked Setup"):
                os.remove(LOCK_FILE)
                st.info("🔓 Setup reset. You can lock new legs.")
