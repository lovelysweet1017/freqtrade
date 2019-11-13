import logging
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from freqtrade.configuration import TimeRange
from freqtrade.data import history
from freqtrade.data.btanalysis import (combine_tickers_with_mean,
                                       create_cum_profit,
                                       extract_trades_of_period, load_trades)
from freqtrade.resolvers import StrategyResolver

logger = logging.getLogger(__name__)


try:
    from plotly.subplots import make_subplots
    from plotly.offline import plot
    import plotly.graph_objects as go
except ImportError:
    logger.exception("Module plotly not found \n Please install using `pip3 install plotly`")
    exit(1)


def init_plotscript(config):
    """
    Initialize objects needed for plotting
    :return: Dict with tickers, trades and pairs
    """

    if "pairs" in config:
        pairs = config["pairs"]
    else:
        pairs = config["exchange"]["pair_whitelist"]

    # Set timerange to use
    timerange = TimeRange.parse_timerange(config.get("timerange"))

    tickers = history.load_data(
        datadir=Path(str(config.get("datadir"))),
        pairs=pairs,
        timeframe=config.get('ticker_interval', '5m'),
        timerange=timerange,
    )

    trades = load_trades(config['trade_source'],
                         db_url=config.get('db_url'),
                         exportfilename=config.get('exportfilename'),
                         )

    return {"tickers": tickers,
            "trades": trades,
            "pairs": pairs,
            }


def add_indicators(fig, row, indicators: List[str], data: pd.DataFrame) -> make_subplots:
    """
    Generator all the indicator selected by the user for a specific row
    :param fig: Plot figure to append to
    :param row: row number for this plot
    :param indicators: List of indicators present in the dataframe
    :param data: candlestick DataFrame
    """
    for indicator in indicators:
        if indicator in data:
            scatter = go.Scatter(
                x=data['date'],
                y=data[indicator].values,
                mode='lines',
                name=indicator
            )
            fig.add_trace(scatter, row, 1)
        else:
            logger.info(
                'Indicator "%s" ignored. Reason: This indicator is not found '
                'in your strategy.',
                indicator
            )

    return fig


def add_profit(fig, row, data: pd.DataFrame, column: str, name: str) -> make_subplots:
    """
    Add profit-plot
    :param fig: Plot figure to append to
    :param row: row number for this plot
    :param data: candlestick DataFrame
    :param column: Column to use for plot
    :param name: Name to use
    :return: fig with added profit plot
    """
    profit = go.Scatter(
        x=data.index,
        y=data[column],
        name=name,
    )
    fig.add_trace(profit, row, 1)

    return fig


def plot_trades(fig, trades: pd.DataFrame) -> make_subplots:
    """
    Add trades to "fig"
    """
    # Trades can be empty
    if trades is not None and len(trades) > 0:
        trade_buys = go.Scatter(
            x=trades["open_time"],
            y=trades["open_rate"],
            mode='markers',
            name='trade_buy',
            marker=dict(
                symbol='square-open',
                size=11,
                line=dict(width=2),
                color='green'
            )
        )
        # Create description for sell summarizing the trade
        desc = trades.apply(lambda row: f"{round(row['profitperc'], 3)}%, {row['sell_reason']}, "
                                        f"{row['duration']}min",
                            axis=1)
        trade_sells = go.Scatter(
            x=trades["close_time"],
            y=trades["close_rate"],
            text=desc,
            mode='markers',
            name='trade_sell',
            marker=dict(
                symbol='square-open',
                size=11,
                line=dict(width=2),
                color='red'
            )
        )
        fig.add_trace(trade_buys, 1, 1)
        fig.add_trace(trade_sells, 1, 1)
    else:
        logger.warning("No trades found.")
    return fig


def generate_candlestick_graph(pair: str, data: pd.DataFrame, trades: pd.DataFrame = None,
                               indicators1: List[str] = [],
                               indicators2: List[str] = [],) -> go.Figure:
    """
    Generate the graph from the data generated by Backtesting or from DB
    Volume will always be ploted in row2, so Row 1 and 3 are to our disposal for custom indicators
    :param pair: Pair to Display on the graph
    :param data: OHLCV DataFrame containing indicators and buy/sell signals
    :param trades: All trades created
    :param indicators1: List containing Main plot indicators
    :param indicators2: List containing Sub plot indicators
    :return: None
    """

    # Define the graph
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        row_width=[1, 1, 4],
        vertical_spacing=0.0001,
    )
    fig['layout'].update(title=pair)
    fig['layout']['yaxis1'].update(title='Price')
    fig['layout']['yaxis2'].update(title='Volume')
    fig['layout']['yaxis3'].update(title='Other')
    fig['layout']['xaxis']['rangeslider'].update(visible=False)

    # Common information
    candles = go.Candlestick(
        x=data.date,
        open=data.open,
        high=data.high,
        low=data.low,
        close=data.close,
        name='Price'
    )
    fig.add_trace(candles, 1, 1)

    if 'buy' in data.columns:
        df_buy = data[data['buy'] == 1]
        if len(df_buy) > 0:
            buys = go.Scatter(
                x=df_buy.date,
                y=df_buy.close,
                mode='markers',
                name='buy',
                marker=dict(
                    symbol='triangle-up-dot',
                    size=9,
                    line=dict(width=1),
                    color='green',
                )
            )
            fig.add_trace(buys, 1, 1)
        else:
            logger.warning("No buy-signals found.")

    if 'sell' in data.columns:
        df_sell = data[data['sell'] == 1]
        if len(df_sell) > 0:
            sells = go.Scatter(
                x=df_sell.date,
                y=df_sell.close,
                mode='markers',
                name='sell',
                marker=dict(
                    symbol='triangle-down-dot',
                    size=9,
                    line=dict(width=1),
                    color='red',
                )
            )
            fig.add_trace(sells, 1, 1)
        else:
            logger.warning("No sell-signals found.")

    # TODO: Figure out why scattergl causes problems plotly/plotly.js#2284
    if 'bb_lowerband' in data and 'bb_upperband' in data:
        bb_lower = go.Scatter(
            x=data.date,
            y=data.bb_lowerband,
            showlegend=False,
            line={'color': 'rgba(255,255,255,0)'},
        )
        bb_upper = go.Scatter(
            x=data.date,
            y=data.bb_upperband,
            name='Bollinger Band',
            fill="tonexty",
            fillcolor="rgba(0,176,246,0.2)",
            line={'color': 'rgba(255,255,255,0)'},
        )
        fig.add_trace(bb_lower, 1, 1)
        fig.add_trace(bb_upper, 1, 1)
        if 'bb_upperband' in indicators1 and 'bb_lowerband' in indicators1:
            indicators1.remove('bb_upperband')
            indicators1.remove('bb_lowerband')

    # Add indicators to main plot
    fig = add_indicators(fig=fig, row=1, indicators=indicators1, data=data)

    fig = plot_trades(fig, trades)

    # Volume goes to row 2
    volume = go.Bar(
        x=data['date'],
        y=data['volume'],
        name='Volume',
        marker_color='DarkSlateGrey',
        marker_line_color='DarkSlateGrey'
        )
    fig.add_trace(volume, 2, 1)

    # Add indicators to separate row
    fig = add_indicators(fig=fig, row=3, indicators=indicators2, data=data)

    return fig


def generate_profit_graph(pairs: str, tickers: Dict[str, pd.DataFrame],
                          trades: pd.DataFrame, timeframe: str) -> go.Figure:
    # Combine close-values for all pairs, rename columns to "pair"
    df_comb = combine_tickers_with_mean(tickers, "close")

    # Add combined cumulative profit
    df_comb = create_cum_profit(df_comb, trades, 'cum_profit', timeframe)

    # Plot the pairs average close prices, and total profit growth
    avgclose = go.Scatter(
        x=df_comb.index,
        y=df_comb['mean'],
        name='Avg close price',
    )

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        row_width=[1, 1, 1],
                        vertical_spacing=0.05,
                        subplot_titles=["AVG Close Price", "Combined Profit", "Profit per pair"])
    fig['layout'].update(title="Freqtrade Profit plot")
    fig['layout']['yaxis1'].update(title='Price')
    fig['layout']['yaxis2'].update(title='Profit')
    fig['layout']['yaxis3'].update(title='Profit')
    fig['layout']['xaxis']['rangeslider'].update(visible=False)

    fig.add_trace(avgclose, 1, 1)
    fig = add_profit(fig, 2, df_comb, 'cum_profit', 'Profit')

    for pair in pairs:
        profit_col = f'cum_profit_{pair}'
        df_comb = create_cum_profit(df_comb, trades[trades['pair'] == pair], profit_col, timeframe)

        fig = add_profit(fig, 3, df_comb, profit_col, f"Profit {pair}")

    return fig


def generate_plot_filename(pair, timeframe) -> str:
    """
    Generate filenames per pair/timeframe to be used for storing plots
    """
    pair_name = pair.replace("/", "_")
    file_name = 'freqtrade-plot-' + pair_name + '-' + timeframe + '.html'

    logger.info('Generate plot file for %s', pair)

    return file_name


def store_plot_file(fig, filename: str, directory: Path, auto_open: bool = False) -> None:
    """
    Generate a plot html file from pre populated fig plotly object
    :param fig: Plotly Figure to plot
    :param filename: Name to store the file as
    :param directory: Directory to store the file in
    :param auto_open: Automatically open files saved
    :return: None
    """
    directory.mkdir(parents=True, exist_ok=True)

    _filename = directory.joinpath(filename)
    plot(fig, filename=str(_filename),
         auto_open=auto_open)
    logger.info(f"Stored plot as {_filename}")


def load_and_plot_trades(config: Dict[str, Any]):
    """
    From configuration provided
    - Initializes plot-script
    - Get tickers data
    - Generate Dafaframes populated with indicators and signals based on configured strategy
    - Load trades excecuted during the selected period
    - Generate Plotly plot objects
    - Generate plot files
    :return: None
    """
    strategy = StrategyResolver(config).strategy

    plot_elements = init_plotscript(config)
    trades = plot_elements['trades']
    pair_counter = 0
    for pair, data in plot_elements["tickers"].items():
        pair_counter += 1
        logger.info("analyse pair %s", pair)
        tickers = {}
        tickers[pair] = data

        dataframe = strategy.analyze_ticker(tickers[pair], {'pair': pair})
        trades_pair = trades.loc[trades['pair'] == pair]
        trades_pair = extract_trades_of_period(dataframe, trades_pair)

        fig = generate_candlestick_graph(
            pair=pair,
            data=dataframe,
            trades=trades_pair,
            indicators1=config["indicators1"],
            indicators2=config["indicators2"],
        )

        store_plot_file(fig, filename=generate_plot_filename(pair, config['ticker_interval']),
                        directory=config['user_data_dir'] / "plot")

    logger.info('End of plotting process. %s plots generated', pair_counter)


def plot_profit(config: Dict[str, Any]) -> None:
    """
    Plots the total profit for all pairs.
    Note, the profit calculation isn't realistic.
    But should be somewhat proportional, and therefor useful
    in helping out to find a good algorithm.
    """
    plot_elements = init_plotscript(config)
    trades = load_trades(config['trade_source'],
                         db_url=str(config.get('db_url')),
                         exportfilename=str(config.get('exportfilename')),
                         )
    # Filter trades to relevant pairs
    trades = trades[trades['pair'].isin(plot_elements["pairs"])]
    # Create an average close price of all the pairs that were involved.
    # this could be useful to gauge the overall market trend
    fig = generate_profit_graph(plot_elements["pairs"], plot_elements["tickers"],
                                trades, config.get('ticker_interval', '5m'))
    store_plot_file(fig, filename='freqtrade-profit-plot.html',
                    directory=config['user_data_dir'] / "plot", auto_open=True)
