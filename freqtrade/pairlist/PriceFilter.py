"""
Price pair list filter
"""
import logging
from typing import Any, Dict

from freqtrade.exceptions import OperationalException
from freqtrade.pairlist.IPairList import IPairList


logger = logging.getLogger(__name__)


class PriceFilter(IPairList):

    def __init__(self, exchange, pairlistmanager,
                 config: Dict[str, Any], pairlistconfig: Dict[str, Any],
                 pairlist_pos: int) -> None:
        super().__init__(exchange, pairlistmanager, config, pairlistconfig, pairlist_pos)

        self._low_price_ratio = pairlistconfig.get('low_price_ratio', 0)
        if self._low_price_ratio < 0:
            raise OperationalException("PriceFilter requires low_price_ratio to be >= 0")
        self._min_price = pairlistconfig.get('min_price', 0)
        if self._min_price < 0:
            raise OperationalException("PriceFilter requires min_price to be >= 0")
        self._max_price = pairlistconfig.get('max_price', 0)
        if self._max_price < 0:
            raise OperationalException("PriceFilter requires max_price to be >= 0")
        self._enabled = ((self._low_price_ratio > 0) or
                         (self._min_price > 0) or
                         (self._max_price > 0))

    @property
    def needstickers(self) -> bool:
        """
        Boolean property defining if tickers are necessary.
        If no Pairlist requires tickers, an empty Dict is passed
        as tickers argument to filter_pairlist
        """
        return True

    def short_desc(self) -> str:
        """
        Short whitelist method description - used for startup-messages
        """
        active_price_filters = []
        if self._low_price_ratio != 0:
            active_price_filters.append(f"below {self._low_price_ratio * 100}%")
        if self._min_price != 0:
            active_price_filters.append(f"below {self._min_price:.8f}")
        if self._max_price != 0:
            active_price_filters.append(f"above {self._max_price:.8f}")

        if len(active_price_filters):
            return f"{self.name} - Filtering pairs priced {' or '.join(active_price_filters)}."

        return f"{self.name} - No price filters configured."

    def _validate_pair(self, ticker) -> bool:
        """
        Check if if one price-step (pip) is > than a certain barrier.
        :param ticker: ticker dict as returned from ccxt.load_markets()
        :return: True if the pair can stay, false if it should be removed
        """
        if ticker['last'] is None or ticker['last'] == 0:
            self.log_once(f"Removed {ticker['symbol']} from whitelist, because "
                          "ticker['last'] is empty (Usually no trade in the last 24h).",
                          logger.info)
            return False

        # Perform low_price_ratio check.
        if self._low_price_ratio != 0:
            compare = self._exchange.price_get_one_pip(ticker['symbol'], ticker['last'])
            changeperc = compare / ticker['last']
            if changeperc > self._low_price_ratio:
                self.log_once(f"Removed {ticker['symbol']} from whitelist, "
                              f"because 1 unit is {changeperc * 100:.3f}%", logger.info)
                return False

        # Perform min_price check.
        if self._min_price != 0:
            if ticker['last'] < self._min_price:
                self.log_once(f"Removed {ticker['symbol']} from whitelist, "
                              f"because last price < {self._min_price:.8f}", logger.info)
                return False

        # Perform max_price check.
        if self._max_price != 0:
            if ticker['last'] > self._max_price:
                self.log_once(f"Removed {ticker['symbol']} from whitelist, "
                              f"because last price > {self._max_price:.8f}", logger.info)
                return False

        return True
