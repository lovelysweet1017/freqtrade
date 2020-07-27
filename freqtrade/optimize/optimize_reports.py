import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from arrow import Arrow
from pandas import DataFrame
from numpy import int64
from tabulate import tabulate

from freqtrade.constants import DATETIME_PRINT_FORMAT, LAST_BT_RESULT_FN
from freqtrade.data.btanalysis import calculate_max_drawdown, calculate_market_change
from freqtrade.misc import file_dump_json

logger = logging.getLogger(__name__)


def store_backtest_stats(recordfilename: Path, stats: Dict[str, DataFrame]) -> None:

    if recordfilename.is_dir():
        filename = (recordfilename /
                    f'backtest-result-{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.json')
    else:
        filename = Path.joinpath(
            recordfilename.parent,
            f'{recordfilename.stem}-{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}'
            ).with_suffix(recordfilename.suffix)
    file_dump_json(filename, stats)

    latest_filename = Path.joinpath(filename.parent, LAST_BT_RESULT_FN)
    file_dump_json(latest_filename, {'latest_backtest': str(filename.name)})


def backtest_result_to_list(results: DataFrame) -> List[List]:
    """
    Converts a list of Backtest-results to list
    :param results: Dataframe containing results for one strategy
    :return: List of Lists containing the trades
    """
    # Return 0 as "index" for compatibility reasons (for now)
    # TODO: Evaluate if we can remove this
    return [[t.pair, t.profit_percent, t.open_date.timestamp(),
             t.close_date.timestamp(), 0, t.trade_duration,
             t.open_rate, t.close_rate, t.open_at_end, t.sell_reason.value]
            for index, t in results.iterrows()]


def _get_line_floatfmt() -> List[str]:
    """
    Generate floatformat (goes in line with _generate_result_line())
    """
    return ['s', 'd', '.2f', '.2f', '.8f', '.2f', 'd', 'd', 'd', 'd']


def _get_line_header(first_column: str, stake_currency: str) -> List[str]:
    """
    Generate header lines (goes in line with _generate_result_line())
    """
    return [first_column, 'Buys', 'Avg Profit %', 'Cum Profit %',
            f'Tot Profit {stake_currency}', 'Tot Profit %', 'Avg Duration',
            'Wins', 'Draws', 'Losses']


def _generate_result_line(result: DataFrame, max_open_trades: int, first_column: str) -> Dict:
    """
    Generate one result dict, with "first_column" as key.
    """
    return {
        'key': first_column,
        'trades': len(result),
        'profit_mean': result['profit_percent'].mean() if len(result) > 0 else 0.0,
        'profit_mean_pct': result['profit_percent'].mean() * 100.0 if len(result) > 0 else 0.0,
        'profit_sum': result['profit_percent'].sum(),
        'profit_sum_pct': result['profit_percent'].sum() * 100.0,
        'profit_total_abs': result['profit_abs'].sum(),
        'profit_total': result['profit_percent'].sum() / max_open_trades,
        'profit_total_pct': result['profit_percent'].sum() * 100.0 / max_open_trades,
        'duration_avg': str(timedelta(
                            minutes=round(result['trade_duration'].mean()))
                            ) if not result.empty else '0:00',
        # 'duration_max': str(timedelta(
        #                     minutes=round(result['trade_duration'].max()))
        #                     ) if not result.empty else '0:00',
        # 'duration_min': str(timedelta(
        #                     minutes=round(result['trade_duration'].min()))
        #                     ) if not result.empty else '0:00',
        'wins': len(result[result['profit_abs'] > 0]),
        'draws': len(result[result['profit_abs'] == 0]),
        'losses': len(result[result['profit_abs'] < 0]),
    }


def generate_pair_metrics(data: Dict[str, Dict], stake_currency: str, max_open_trades: int,
                          results: DataFrame, skip_nan: bool = False) -> List[Dict]:
    """
    Generates and returns a list  for the given backtest data and the results dataframe
    :param data: Dict of <pair: dataframe> containing data that was used during backtesting.
    :param stake_currency: stake-currency - used to correctly name headers
    :param max_open_trades: Maximum allowed open trades
    :param results: Dataframe containing the backtest results
    :param skip_nan: Print "left open" open trades
    :return: List of Dicts containing the metrics per pair
    """

    tabular_data = []

    for pair in data:
        result = results[results['pair'] == pair]
        if skip_nan and result['profit_abs'].isnull().all():
            continue

        tabular_data.append(_generate_result_line(result, max_open_trades, pair))

    # Append Total
    tabular_data.append(_generate_result_line(results, max_open_trades, 'TOTAL'))
    return tabular_data


def generate_sell_reason_stats(max_open_trades: int, results: DataFrame) -> List[Dict]:
    """
    Generate small table outlining Backtest results
    :param max_open_trades: Max_open_trades parameter
    :param results: Dataframe containing the backtest result for one strategy
    :return: List of Dicts containing the metrics per Sell reason
    """
    tabular_data = []

    for reason, count in results['sell_reason'].value_counts().iteritems():
        result = results.loc[results['sell_reason'] == reason]

        profit_mean = result['profit_percent'].mean()
        profit_sum = result["profit_percent"].sum()
        profit_percent_tot = round(result['profit_percent'].sum() * 100.0 / max_open_trades, 2)

        tabular_data.append(
            {
                'sell_reason': reason.value,
                'trades': count,
                'wins': len(result[result['profit_abs'] > 0]),
                'draws': len(result[result['profit_abs'] == 0]),
                'losses': len(result[result['profit_abs'] < 0]),
                'profit_mean': profit_mean,
                'profit_mean_pct': round(profit_mean * 100, 2),
                'profit_sum': profit_sum,
                'profit_sum_pct': round(profit_sum * 100, 2),
                'profit_total_abs': result['profit_abs'].sum(),
                'profit_total_pct': profit_percent_tot,
            }
        )
    return tabular_data


def generate_strategy_metrics(stake_currency: str, max_open_trades: int,
                              all_results: Dict) -> List[Dict]:
    """
    Generate summary per strategy
    :param stake_currency: stake-currency - used to correctly name headers
    :param max_open_trades: Maximum allowed open trades used for backtest
    :param all_results: Dict of <Strategyname: BacktestResult> containing results for all strategies
    :return: List of Dicts containing the metrics per Strategy
    """

    tabular_data = []
    for strategy, results in all_results.items():
        tabular_data.append(_generate_result_line(results, max_open_trades, strategy))
    return tabular_data


def generate_edge_table(results: dict) -> str:

    floatfmt = ('s', '.10g', '.2f', '.2f', '.2f', '.2f', 'd', 'd', 'd')
    tabular_data = []
    headers = ['Pair', 'Stoploss', 'Win Rate', 'Risk Reward Ratio',
               'Required Risk Reward', 'Expectancy', 'Total Number of Trades',
               'Average Duration (min)']

    for result in results.items():
        if result[1].nb_trades > 0:
            tabular_data.append([
                result[0],
                result[1].stoploss,
                result[1].winrate,
                result[1].risk_reward_ratio,
                result[1].required_risk_reward,
                result[1].expectancy,
                result[1].nb_trades,
                round(result[1].avg_trade_duration)
            ])

    # Ignore type as floatfmt does allow tuples but mypy does not know that
    return tabulate(tabular_data, headers=headers,
                    floatfmt=floatfmt, tablefmt="orgtbl", stralign="right")  # type: ignore


def generate_daily_stats(results: DataFrame) -> Dict[str, Any]:
    daily_profit = results.resample('1d', on='close_date')['profit_percent'].sum()
    worst = min(daily_profit)
    best = max(daily_profit)
    winning_days = sum(daily_profit > 0)
    draw_days = sum(daily_profit == 0)
    losing_days = sum(daily_profit < 0)

    winning_trades = results.loc[results['profit_percent'] > 0]
    losing_trades = results.loc[results['profit_percent'] < 0]

    return {
        'backtest_best_day': best,
        'backtest_worst_day': worst,
        'winning_days': winning_days,
        'draw_days': draw_days,
        'losing_days': losing_days,
        'winner_holding_avg': (timedelta(minutes=round(winning_trades['trade_duration'].mean()))
                               if not winning_trades.empty else timedelta()),
        'loser_holding_avg': (timedelta(minutes=round(losing_trades['trade_duration'].mean()))
                              if not losing_trades.empty else timedelta()),
    }


def generate_backtest_stats(config: Dict, btdata: Dict[str, DataFrame],
                            all_results: Dict[str, DataFrame],
                            min_date: Arrow, max_date: Arrow
                            ) -> Dict[str, Any]:
    """
    :param config: Configuration object used for backtest
    :param btdata: Backtest data
    :param all_results: backtest result - dictionary with { Strategy: results}.
    :param min_date: Backtest start date
    :param max_date: Backtest end date
    :return:
    Dictionary containing results per strategy and a stratgy summary.
    """
    stake_currency = config['stake_currency']
    max_open_trades = config['max_open_trades']
    result: Dict[str, Any] = {'strategy': {}}
    market_change = calculate_market_change(btdata, 'close')

    for strategy, results in all_results.items():

        pair_results = generate_pair_metrics(btdata, stake_currency=stake_currency,
                                             max_open_trades=max_open_trades,
                                             results=results, skip_nan=False)
        sell_reason_stats = generate_sell_reason_stats(max_open_trades=max_open_trades,
                                                       results=results)
        left_open_results = generate_pair_metrics(btdata, stake_currency=stake_currency,
                                                  max_open_trades=max_open_trades,
                                                  results=results.loc[results['open_at_end']],
                                                  skip_nan=True)
        daily_stats = generate_daily_stats(results)

        results['open_timestamp'] = results['open_date'].astype(int64) // 1e6
        results['close_timestamp'] = results['close_date'].astype(int64) // 1e6

        backtest_days = (max_date - min_date).days
        strat_stats = {
            'trades': results.to_dict(orient='records'),
            'results_per_pair': pair_results,
            'sell_reason_summary': sell_reason_stats,
            'left_open_trades': left_open_results,
            'total_trades': len(results),
            'backtest_start': min_date.datetime,
            'backtest_start_ts': min_date.timestamp * 1000,
            'backtest_end': max_date.datetime,
            'backtest_end_ts': max_date.timestamp * 1000,
            'backtest_days': backtest_days,

            'trades_per_day': round(len(results) / backtest_days, 2) if backtest_days > 0 else None,
            'market_change': market_change,
            'pairlist': list(btdata.keys()),
            'stake_amount': config['stake_amount'],
            'stake_currency': config['stake_currency'],
            'max_open_trades': config['max_open_trades'],
            **daily_stats,
        }
        result['strategy'][strategy] = strat_stats

        try:
            max_drawdown, drawdown_start, drawdown_end = calculate_max_drawdown(
                results, value_col='profit_percent')
            strat_stats.update({
                'max_drawdown': max_drawdown,
                'drawdown_start': drawdown_start,
                'drawdown_start_ts': drawdown_start.timestamp() * 1000,
                'drawdown_end': drawdown_end,
                'drawdown_end_ts': drawdown_end.timestamp() * 1000,
            })
        except ValueError:
            strat_stats.update({
                'max_drawdown': 0.0,
                'drawdown_start': datetime(1970, 1, 1, tzinfo=timezone.utc),
                'drawdown_start_ts': 0,
                'drawdown_end': datetime(1970, 1, 1, tzinfo=timezone.utc),
                'drawdown_end_ts': 0,
            })

    strategy_results = generate_strategy_metrics(stake_currency=stake_currency,
                                                 max_open_trades=max_open_trades,
                                                 all_results=all_results)

    result['strategy_comparison'] = strategy_results

    return result


###
# Start output section
###

def text_table_bt_results(pair_results: List[Dict[str, Any]], stake_currency: str) -> str:
    """
    Generates and returns a text table for the given backtest data and the results dataframe
    :param pair_results: List of Dictionaries - one entry per pair + final TOTAL row
    :param stake_currency: stake-currency - used to correctly name headers
    :return: pretty printed table with tabulate as string
    """

    headers = _get_line_header('Pair', stake_currency)
    floatfmt = _get_line_floatfmt()
    output = [[
        t['key'], t['trades'], t['profit_mean_pct'], t['profit_sum_pct'], t['profit_total_abs'],
        t['profit_total_pct'], t['duration_avg'], t['wins'], t['draws'], t['losses']
    ] for t in pair_results]
    # Ignore type as floatfmt does allow tuples but mypy does not know that
    return tabulate(output, headers=headers,
                    floatfmt=floatfmt, tablefmt="orgtbl", stralign="right")


def text_table_sell_reason(sell_reason_stats: List[Dict[str, Any]], stake_currency: str) -> str:
    """
    Generate small table outlining Backtest results
    :param sell_reason_stats: Sell reason metrics
    :param stake_currency: Stakecurrency used
    :return: pretty printed table with tabulate as string
    """
    headers = [
        'Sell Reason',
        'Sells',
        'Wins',
        'Draws',
        'Losses',
        'Avg Profit %',
        'Cum Profit %',
        f'Tot Profit {stake_currency}',
        'Tot Profit %',
    ]

    output = [[
        t['sell_reason'], t['trades'], t['wins'], t['draws'], t['losses'],
        t['profit_mean_pct'], t['profit_sum_pct'], t['profit_total_abs'], t['profit_total_pct'],
    ] for t in sell_reason_stats]
    return tabulate(output, headers=headers, tablefmt="orgtbl", stralign="right")


def text_table_strategy(strategy_results, stake_currency: str) -> str:
    """
    Generate summary table per strategy
    :param stake_currency: stake-currency - used to correctly name headers
    :param max_open_trades: Maximum allowed open trades used for backtest
    :param all_results: Dict of <Strategyname: BacktestResult> containing results for all strategies
    :return: pretty printed table with tabulate as string
    """
    floatfmt = _get_line_floatfmt()
    headers = _get_line_header('Strategy', stake_currency)

    output = [[
        t['key'], t['trades'], t['profit_mean_pct'], t['profit_sum_pct'], t['profit_total_abs'],
        t['profit_total_pct'], t['duration_avg'], t['wins'], t['draws'], t['losses']
    ] for t in strategy_results]
    # Ignore type as floatfmt does allow tuples but mypy does not know that
    return tabulate(output, headers=headers,
                    floatfmt=floatfmt, tablefmt="orgtbl", stralign="right")


def text_table_add_metrics(strat_results: Dict) -> str:
    if len(strat_results['trades']) > 0:
        min_trade = min(strat_results['trades'], key=lambda x: x['open_date'])
        metrics = [
            ('Backtesting from', strat_results['backtest_start'].strftime(DATETIME_PRINT_FORMAT)),
            ('Backtesting to', strat_results['backtest_end'].strftime(DATETIME_PRINT_FORMAT)),
            ('Total trades', strat_results['total_trades']),
            ('First trade', min_trade['open_date'].strftime(DATETIME_PRINT_FORMAT)),
            ('First trade Pair', min_trade['pair']),
            ('Trades per day', strat_results['trades_per_day']),
            ('Best day', f"{round(strat_results['backtest_best_day'] * 100, 2)}%"),
            ('Worst day', f"{round(strat_results['backtest_worst_day'] * 100, 2)}%"),
            ('Days win/draw/lose', f"{strat_results['winning_days']} / "
                f"{strat_results['draw_days']} / {strat_results['losing_days']}"),
            ('Avg. Duration Winners', f"{strat_results['winner_holding_avg']}"),
            ('Avg. Duration Loser', f"{strat_results['loser_holding_avg']}"),
            ('', ''),  # Empty line to improve readability
            ('Max Drawdown', f"{round(strat_results['max_drawdown'] * 100, 2)}%"),
            ('Drawdown Start', strat_results['drawdown_start'].strftime(DATETIME_PRINT_FORMAT)),
            ('Drawdown End', strat_results['drawdown_end'].strftime(DATETIME_PRINT_FORMAT)),
            ('Market change', f"{round(strat_results['market_change'] * 100, 2)}%"),
        ]

        return tabulate(metrics, headers=["Metric", "Value"], tablefmt="orgtbl")
    else:
        return ''


def show_backtest_results(config: Dict, backtest_stats: Dict):
    stake_currency = config['stake_currency']

    for strategy, results in backtest_stats['strategy'].items():

        # Print results
        print(f"Result for strategy {strategy}")
        table = text_table_bt_results(results['results_per_pair'], stake_currency=stake_currency)
        if isinstance(table, str):
            print(' BACKTESTING REPORT '.center(len(table.splitlines()[0]), '='))
        print(table)

        table = text_table_sell_reason(sell_reason_stats=results['sell_reason_summary'],
                                       stake_currency=stake_currency)
        if isinstance(table, str) and len(table) > 0:
            print(' SELL REASON STATS '.center(len(table.splitlines()[0]), '='))
        print(table)

        table = text_table_bt_results(results['left_open_trades'], stake_currency=stake_currency)
        if isinstance(table, str) and len(table) > 0:
            print(' LEFT OPEN TRADES REPORT '.center(len(table.splitlines()[0]), '='))
        print(table)

        table = text_table_add_metrics(results)
        if isinstance(table, str) and len(table) > 0:
            print(' SUMMARY METRICS '.center(len(table.splitlines()[0]), '='))
        print(table)

        if isinstance(table, str) and len(table) > 0:
            print('=' * len(table.splitlines()[0]))
        print()

    if len(backtest_stats['strategy']) > 1:
        # Print Strategy summary table

        table = text_table_strategy(backtest_stats['strategy_comparison'], stake_currency)
        print(' STRATEGY SUMMARY '.center(len(table.splitlines()[0]), '='))
        print(table)
        print('=' * len(table.splitlines()[0]))
        print('\nFor more details, please look at the detail tables above')
