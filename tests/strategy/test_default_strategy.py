from datetime import datetime

from pandas import DataFrame

from freqtrade.persistence.models import Trade

from .strats.default_strategy import DefaultStrategy


def test_default_strategy_structure():
    assert hasattr(DefaultStrategy, 'minimal_roi')
    assert hasattr(DefaultStrategy, 'stoploss')
    assert hasattr(DefaultStrategy, 'timeframe')
    assert hasattr(DefaultStrategy, 'populate_indicators')
    assert hasattr(DefaultStrategy, 'populate_buy_trend')
    assert hasattr(DefaultStrategy, 'populate_sell_trend')
    assert hasattr(DefaultStrategy, 'populate_short_trend')
    assert hasattr(DefaultStrategy, 'populate_exit_short_trend')


def test_default_strategy(result, fee):
    strategy = DefaultStrategy({})

    metadata = {'pair': 'ETH/BTC'}
    assert type(strategy.minimal_roi) is dict
    assert type(strategy.stoploss) is float
    assert type(strategy.timeframe) is str
    indicators = strategy.populate_indicators(result, metadata)
    assert type(indicators) is DataFrame
    assert type(strategy.populate_buy_trend(indicators, metadata)) is DataFrame
    assert type(strategy.populate_sell_trend(indicators, metadata)) is DataFrame
    # TODO-lev: I think these two should be commented out in the strategy by default
    # TODO-lev: so they can be tested, but the tests can't really remain
    assert type(strategy.populate_short_trend(indicators, metadata)) is DataFrame
    assert type(strategy.populate_exit_short_trend(indicators, metadata)) is DataFrame

    trade = Trade(
        open_rate=19_000,
        amount=0.1,
        pair='ETH/BTC',
        fee_open=fee.return_value
    )

    assert strategy.confirm_trade_entry(pair='ETH/BTC', order_type='limit', amount=0.1,
                                        rate=20000, time_in_force='gtc',
                                        is_short=False, current_time=datetime.utcnow()) is True

    assert strategy.confirm_trade_exit(pair='ETH/BTC', trade=trade, order_type='limit', amount=0.1,
                                       rate=20000, time_in_force='gtc', sell_reason='roi',
                                       is_short=False, current_time=datetime.utcnow()) is True

    # TODO-lev: Test for shorts?
    assert strategy.custom_stoploss(pair='ETH/BTC', trade=trade, current_time=datetime.now(),
                                    current_rate=20_000, current_profit=0.05) == strategy.stoploss

    short_trade = Trade(
        open_rate=21_000,
        amount=0.1,
        pair='ETH/BTC',
        fee_open=fee.return_value
    )

    assert strategy.confirm_trade_entry(pair='ETH/BTC', order_type='limit', amount=0.1,
                                        rate=20000, time_in_force='gtc',
                                        is_short=True, current_time=datetime.utcnow()) is True

    assert strategy.confirm_trade_exit(pair='ETH/BTC', trade=short_trade, order_type='limit',
                                       amount=0.1, rate=20000, time_in_force='gtc',
                                       sell_reason='roi', is_short=True,
                                       current_time=datetime.utcnow()) is True
