import datetime
import glob
import json
import logging
import os
import sys
import time
import requests
import yfinance as yf

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SYMBOLS_DIR = os.path.join(SCRIPT_DIR, 'symbols')
DIST_DIR = os.path.join(SCRIPT_DIR, 'dist')


def get_latest_user_agent(operating_system='windows', browser='chrome'):
    url = f'https://jnrbsn.github.io/user-agents/user-agents.json'
    r = requests.get(url)
    r.raise_for_status()
    user_agents = r.json()

    for user_agent in user_agents:
        if operating_system.lower() in user_agent.lower() and browser.lower() in user_agent.lower():
            return user_agent

    return None


def main():
    failed = []
    logging.info(f"reading symbols *.json files in {SYMBOLS_DIR} ...")
    for symbol_track_file_path in glob.glob(os.path.join(SYMBOLS_DIR, '*.json'), recursive=True):
        logging.info(f"processing {symbol_track_file_path} ...")

        try:
            with open(symbol_track_file_path) as f:
                symbol_track_info = json.load(f)

            symbol_price = 0
            symbol_price_date = ''

            symbol_id = symbol_track_info['id']
            symbol = symbol_track_info['symbol']
            currency = symbol_track_info['currency']
            user_agent_header = get_latest_user_agent(operating_system='windows', browser='chrome')

            if symbol_track_info['source'] == 'justetf':
                url = f'https://www.justetf.com/api/etfs/{symbol}/quote?locale=en&currency={currency}&isin={symbol}'
                r = requests.get(url, headers={'User-Agent': user_agent_header, 'Accept': 'application/json'})
                r.raise_for_status()
                symbol_info = r.json()
                symbol_price = symbol_info['latestQuote']['raw']
                symbol_price_date = symbol_info['latestQuoteDate']

            elif symbol_track_info['source'] == 'yahoo_finance':
                ticker_yahoo = yf.Ticker(symbol)
                symbol_info = ticker_yahoo.history()
                symbol_price = symbol_info['Close'].iloc[-1]
                symbol_price_date = symbol_info['Close'].index[-1]
                symbol_price_date = datetime.datetime.strftime(symbol_price_date, '%Y-%m-%d')

            elif symbol_track_info['source'] == 'issa':
                # Call the TASE APIs directly; loading the TASE sites through selenium-wire's
                # proxy gets ERR_CONNECTION_CLOSED from GitHub runners.
                if symbol_track_info['type'] == 'etf':
                    url = f'https://api.tase.co.il/api/company/securitydata?securityId={symbol}&lang=0'
                    referer = 'https://market.tase.co.il/'
                else:
                    url = f'https://maya.tase.co.il/api/v1/funds/mutual/{symbol}'
                    referer = 'https://maya.tase.co.il/'

                for attempt in range(1, 6):
                    try:
                        r = requests.get(url, headers={'User-Agent': user_agent_header, 'Referer': referer}, timeout=30)
                        r.raise_for_status()
                        response = r.json()
                        break
                    except Exception:
                        if attempt == 5:
                            raise
                        logging.warning(f'attempt {attempt} for {symbol} failed, retrying ...')
                        time.sleep(10 * attempt)

                if symbol_track_info['type'] == 'etf':
                    symbol_price = response['LastRate'] / 100  # ILA -> ILS
                    symbol_price_date = datetime.datetime.strptime(response['TradeDate'], "%d/%m/%Y").strftime('%Y-%m-%d')
                else:
                    symbol_price = response['purchasePrice'] / 100  # ILA -> ILS
                    symbol_price_date = response['ratesAsOf']

            if not symbol_price:
                raise Exception(f'Failed to get price for {symbol}')

            symbol_dist_dir = os.path.join(DIST_DIR, symbol_id)
            os.makedirs(symbol_dist_dir, exist_ok=True)
            symbol_track_info['price'] = symbol_price
            symbol_track_info['price_date'] = symbol_price_date

            with open(os.path.join(symbol_dist_dir, 'price'), 'w+') as f:
                f.write(str(symbol_price))

            with open(os.path.join(symbol_dist_dir, 'currency'), 'w+') as f:
                f.write(currency)

            with open(os.path.join(symbol_dist_dir, 'date'), 'w+') as f:
                f.write(symbol_price_date)

            with open(os.path.join(symbol_dist_dir, 'info.json'), 'w+') as f:
                json.dump(symbol_track_info, f)

            logging.info(f'symbol "{symbol_id}" update completed. price: {symbol_price} {currency} date: {symbol_price_date}')

        except Exception as e:
            logging.exception(f'Failed to process {symbol_track_file_path}')
            failed.append(symbol_track_file_path)

    return failed


if __name__ == '__main__':
    failed = main()
    if failed:
        logging.error(f'{len(failed)} symbol(s) failed: {failed}')
        sys.exit(1)
