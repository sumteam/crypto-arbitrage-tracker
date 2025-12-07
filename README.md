## Overview
This project provides a real-time market tracking solution for specific cryptocurrency pairs on the Binance exchange. It uses Asynchronous I/O (asyncio) to fetch historical data via the REST API and live candlestick data via WebSockets. The collected data is then processed and fed into the sumtyme API for analysis, with the results logged to per-ticker CSV files.

## Project 
This tracker identifies opportunities based on the underlying structure of identical crypto instruments denominated in different currencies. It uses the directional shift observed in one asset pair to anticipate the same directional change in the related instrument.

## Features
- Real-time Data Streaming: Connects to Binance WebSockets for live candlestick updates.
- Historical Data Ingestion: Fetches up to 5000 historical k-lines from the Binance REST API for initial setup.
- Asynchronous Processing: Uses asyncio and asyncio.to_thread to handle blocking network and file I/O calls (e.g. historical data fetch, sumtyme API calls, and CSV logging) efficiently.
- sumtyme Integration: Calls the external sumtyme forecast API to generate chain predictions on new candle data.
- CSV Logging: Logs the date/time, ticker, and predicted chain outcome to separate ticker-specific CSV files.


## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/sumteam/crypto-arbitrage-tracker
    cd crypto-arbitrage-tracker
    ```
2.  **Install dependencies:**
    All required Python packages are specified in the `requirements.txt` file. Install them using `pip`:

    ```bash
    pip install -r requirements.txt
    ```

## Configuration

The main configuration is done within the `run_main` async function:

| Variable | Description | Example Value |
| :--- | :--- | :--- |
| `TICKERS` | List of Binance trading pairs to track. | `["BTCUSDT", "BTCJPY"]` |
| `TIMEFRAMES` | List of K-line intervals to track (e.g., '1m', '5m', '1h'). | `['1m']` |
| `API_KEY` | Your **sumtyme API Key** (required for forecasting). | `"xxxxxxxxx"` |


## Usage
To start the real-time tracker, run the main Python file:

```bash
python main.py
```

The application will:

- Fetch historical data for all configured tickers and timeframes.

- Start dedicated WebSocket connections for each ticker/timeframe stream.

- Log connection status and new candle updates to the console.

- Write forecast results to CSV files like BTCUSDT_chain_log.csv.

## Analysis Type Configuration

The analysis type is controlled by changing the reasoning variable on line 175 of the main.py file.

- 'proactive': Acts early, relying on minimal initial information. 
- 'reactive': Waits for sufficient evidence before taking action.

## Output

Forecast results are stored in **CSV files** in the same directory, named after the ticker (e.g. `BTCUSDT_chain_log.csv`).

| Column Name | Description |
| :--- | :--- |
| `datetime` | Timestamp of the predicted candle (the candle *after* the last received). |
| `ticker` | The trading pair (e.g., BTCUSDT). |
| `chain_detected` | The forecast result from the sumtyme API. |

## Stopping the Tracker

The tracker can be stopped gracefully by pressing **`Ctrl+C`** in the terminal. The `asyncio.gather` call includes `try/except KeyboardInterrupt` handling to allow for a clean exit.

## Cross-Pair Correlation and Lag Analysis

This project's design facilitates the detection of potential **cross-pair arbitrage** or highly-correlated directional trading opportunities by analysing the time-series forecasts of related assets.

Pairs like **BTCUSDT** and **BTCJPY** are intrinsically linked (both trading Bitcoin) and should exhibit a near-perfect correlation in their price movements. A significant directional change identified in one, but not yet reflected in the other, can signal an immediate trading opportunity in the lagging pair.

**Example from the included files:**

Using the sample data around **2025-11-29 06:20:00**:
* The **BTCUSDT** forecast (`BTCUSDT_chain_log_example.csv`) shows an initial directional change to **-1** (a predicted decline) at **06:22:00**.
* The highly correlated **BTCJPY** forecast (`BTCJPY_chain_log_example.csv`) was still **0** (neutral) at the same timestamp.
* The **BTCJPY** change to **-1** only appeared at **06:28:00**, a **6-minute lag**.

This observed lag suggests that an initial signal from the more liquid **BTCUSDT** market could be used to anticipate a subsequent movement in the **BTCJPY** market, thereby providing a short window for a profitable directional or arbitrage trade.
