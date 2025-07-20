# Iron Condor Adjuster

A Streamlit app to monitor and adjust Iron Condor options strategies based on premium difference and 1/3 hedge logic.

## Features

- Automatically detects premium imbalance
- Suggests new hedges using 1/3 premium rule
- Visualizes PnL with Plotly

## Run Locally

```bash
pip install -r requirements.txt
streamlit run iron_condor_adjuster.py
