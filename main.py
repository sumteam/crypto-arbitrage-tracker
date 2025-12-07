import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import asyncio
import websockets
import json
import requests
from typing import List, Dict, Optional, Any
from sumtyme import EIPClient
import re
import os
import csv
from functools import partial

class PerTickerDataLogger:

    # Logger to store API outputs in .csv files

    def __init__(self, ticker: str):
        self.CSV_FILE_PATH = f'{ticker}_chain_log.csv'
        self.ticker = ticker
        self.lock = asyncio.Lock()

    def _write_csv(self, row: Dict[str, str], headers: List[str], file_exists: bool):
        # Synchronous method executed in a separate thread
        try:
            with open(self.CSV_FILE_PATH, 'a', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)

                if not file_exists:
                    writer.writeheader()
                    print(f"Created new CSV file: {self.CSV_FILE_PATH} with headers.")

                writer.writerow(row)

        except IOError as e:
            print(f"Error writing to per-ticker CSV file {self.CSV_FILE_PATH}: {e}")

    async def log_data(self, datetime_key: datetime, chain_detected: str):
        
        async with self.lock:
            
            # Prepare data row for CSV 
            row = {
                'datetime': datetime_key.strftime('%Y-%m-%d %H:%M:%S'),
                'ticker': self.ticker,
                'chain_detected': chain_detected,
            }

            headers = ['datetime', 'ticker', 'chain_detected']
            file_exists = os.path.exists(self.CSV_FILE_PATH)
            
            # Use asyncio.to_thread for the blocking file I/O
            await asyncio.to_thread(self._write_csv, row, headers, file_exists)


class BinanceSumtymeTracker:

    # Class for fetching data from Binance websocket and API processing

    def __init__(self, ticker: str, timeframes: List[str], api_key: str, logger: PerTickerDataLogger):
  
        self.ticker = ticker
        self.timeframes = timeframes
        self.dataframes = {}
        self.ws_connections = {}
        self.logger = logger 

        # Initialise sumtyme client
        self.client = EIPClient(apikey=api_key)

        self.rest_api_base = "https://api.binance.com"
        self.ws_base = "wss://stream.binance.com:9443/ws"

    def parse_timeframe(self, timeframe: str):

        match = re.match(r'(\d+)([smhdMY])', timeframe)

        if not match:
            raise ValueError(f"Invalid timeframe format: {timeframe}")

        value = int(match.group(1))
        unit = match.group(2)
        unit_mapping = {'s': 'seconds', 'm': 'minutes', 'h': 'hours', 'd': 'days', 'M': 'months'}
        binance_mapping = {'s': 's', 'm': 'm', 'h': 'h', 'd': 'd', 'M': 'M'}
        return value, unit_mapping[unit], binance_mapping[unit]

    def get_binance_interval(self, timeframe: str):

        value, _, binance_unit = self.parse_timeframe(timeframe)

        return f"{value}{binance_unit}"

    def _fetch_historical_data_sync(self, timeframe: str):
        # Synchronous method executed in a separate thread

        interval = self.get_binance_interval(timeframe)
        url = f"{self.rest_api_base}/api/v3/klines"
        params = {'symbol': self.ticker, 'interval': interval, 'limit': 1000}
        all_data = []

        # Use a list to hold the end_time to allow modification across loop iterations
        end_time_ref = [None] 

        for _ in range(5):
            # Update params with the next end time if available
            if end_time_ref[0] is not None:
                params['endTime'] = end_time_ref[0] - 1
            
            # This requests.get is the blocking call being isolated
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if not data: 
                break
                
            all_data.extend(data)
            
            # Update end_time_ref for the next request
            end_time_ref[0] = data[0][0] 
            
            if len(all_data) >= 5000: 
                break

        all_data = all_data[-5000:]

        df = pd.DataFrame(all_data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])

        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df[['datetime', 'open', 'high', 'low', 'close']].copy()
        df[['open', 'high', 'low', 'close']] = df[['open', 'high', 'low', 'close']].astype(float)
        df['chain_detected'] = None
        return df

    async def fetch_historical_data(self, timeframe: str):
        # Fetch historical OHLC data from Binance using a separate thread.
        return await asyncio.to_thread(self._fetch_historical_data_sync, timeframe)


    def calculate_next_timestamp(self, last_datetime: datetime, timeframe: str):
        # Calculate the next timestamp based on timeframe.
        value, unit_name, _ = self.parse_timeframe(timeframe)

        if unit_name == 'seconds':
            return last_datetime + timedelta(seconds=value)
        elif unit_name == 'minutes':
            return last_datetime + timedelta(minutes=value)
        elif unit_name == 'hours':
            return last_datetime + timedelta(hours=value)
        elif unit_name == 'days':
            return last_datetime + timedelta(days=value)
        elif unit_name == 'months':
            # Note: For production use, consider using dateutil.relativedelta for robust month arithmetic.
            month = last_datetime.month - 1 + value
            year = last_datetime.year + month // 12
            month = month % 12 + 1
            day = min(last_datetime.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
            return last_datetime.replace(year=year, month=month, day=day)
 
        return last_datetime

    def _call_sumtyme_forecast_sync(self, new_dataframe: pd.DataFrame, timeframe: str):
        # Synchronous method to call the external API
        value, unit_name, _ = self.parse_timeframe(timeframe)
        
        return self.client.ohlc_forecast(
            data_input=new_dataframe,
            interval=value,
            interval_unit=unit_name,
            reasoning_mode='reactive'
        )

    async def process_forecast(self, timeframe: str, new_row: Dict):

        # Process new data, call sumtyme API and record data in the ticker logger.

        df = self.dataframes[timeframe]
        new_df_row = pd.DataFrame([new_row])
        df = pd.concat([df, new_df_row], ignore_index=True)
        self.dataframes[timeframe] = df
        last_5000 = df.tail(5000).copy()
        last_datetime = last_5000['datetime'].iloc[-1]
        next_datetime = self.calculate_next_timestamp(last_datetime, timeframe)
        prediction_row = pd.DataFrame([{'datetime': next_datetime, 'open': 0, 'high': 0, 'low': 0, 'close': 0}])
        new_dataframe = pd.concat([last_5000, prediction_row], ignore_index=True)

        try:
            # Use asyncio.to_thread for the blocking sumtyme API call
            forecast = await asyncio.to_thread(self._call_sumtyme_forecast_sync, new_dataframe, timeframe)

            # Extract chain_detected from forecast
            for datetime_string, chain_detected in forecast.items():
                datetime_obj = pd.to_datetime(datetime_string)
                
                await self.logger.log_data(datetime_obj, chain_detected)

        except Exception as e:
            print(f"Error calling sumtyme API for {self.ticker} {timeframe}: {e}")

    async def handle_websocket(self, timeframe: str):
        interval = self.get_binance_interval(timeframe)
        stream_name = f"{self.ticker.lower()}@kline_{interval}"
        ws_url = f"{self.ws_base}/{stream_name}"
        print(f"Connecting to websocket for {self.ticker} {timeframe}...")

        try:
            async with websockets.connect(ws_url) as websocket:
                self.ws_connections[timeframe] = websocket
                print(f"Connected to websocket for {self.ticker} {timeframe}")

                async for message in websocket:
                    try:
                        data = json.loads(message)
                        kline = data['k']
                        if kline['x']:
                            new_row = {
                                'datetime': pd.to_datetime(kline['t'], unit='ms'),
                                'open': float(kline['o']),
                                'high': float(kline['h']),
                                'low': float(kline['l']),
                                'close': float(kline['c']),
                            }
                            print(f"[{self.ticker} - {timeframe}] New candle: {new_row['datetime']}")
                            await self.process_forecast(timeframe, new_row)
                    except Exception as e:
                        print(f"Error processing websocket message for {self.ticker} {timeframe}: {e}")
        except websockets.exceptions.ConnectionClosedOK:
            print(f"Websocket connection for {self.ticker} {timeframe} closed normally.")
        except Exception as e:
            print(f"Websocket error for {self.ticker} {timeframe}: {e}")
            
    async def run(self):
        print(f"Initialising Binance Tracker for {self.ticker}...")
        print(f"\nFetching historical data for {self.ticker}...")
        
        # Concurrently fetch all historical data using an async task per timeframe
        fetch_tasks = [self.fetch_historical_data(tf) for tf in self.timeframes]
        results = await asyncio.gather(*fetch_tasks)

        for i, timeframe in enumerate(self.timeframes):
            self.dataframes[timeframe] = results[i]
            print(f"Loaded {len(self.dataframes[timeframe])} historical data points for {self.ticker} {timeframe}")

        print(f"\nStarting websocket connections for {self.ticker}...")
        ws_tasks = [self.handle_websocket(tf) for tf in self.timeframes]

        try:
            await asyncio.gather(*ws_tasks)
        except KeyboardInterrupt:
            print(f"\n{self.ticker} Tracker shutting down...")
        except Exception as e:
            print(f"Error in main loop for {self.ticker}: {e}")


async def run_main():
    TICKERS = ["BTCUSDT", "BTCJPY"]
    TIMEFRAMES = ['1m']
    API_KEY = "xxxxxx"

    trackers = []
    for ticker in TICKERS:
        logger = PerTickerDataLogger(ticker=ticker)
        
        tracker = BinanceSumtymeTracker(
            ticker=ticker,
            timeframes=TIMEFRAMES,
            api_key=API_KEY,
            logger=logger
        )
        trackers.append(tracker.run())
    
    try:
        await asyncio.gather(*trackers)
    except KeyboardInterrupt:
        print("\nManual shutdown initiated. Exiting.")
    except Exception as e:
        print(f"An unexpected error occurred during execution: {e}")

if __name__ == "__main__":
       
    asyncio.run(run_main())
                