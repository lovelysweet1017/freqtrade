"""
Static Pair List provider

Provides pair white list as it configured in config
"""
import logging
from typing import Dict, List

from freqtrade.pairlist.IPairList import IPairList


logger = logging.getLogger(__name__)


class StaticPairList(IPairList):

    @property
    def needstickers(self) -> bool:
        """
        Boolean property defining if tickers are necessary.
        If no Pairlist requries tickers, an empty List is passed
        as tickers argument to filter_pairlist
        """
        return False

    def short_desc(self) -> str:
        """
        Short whitelist method description - used for startup-messages
        -> Please overwrite in subclasses
        """
        return f"{self.name}"

    def gen_pairlist(self, cached_pairlist: List[str], tickers: Dict) -> List[str]:
        """
        Generate the pairlist
        :param cached_pairlist: Previously generated pairlist (cached)
        :param tickers: Tickers (from exchange.get_tickers()).
        :return: List of pairs
        """
        return self._whitelist_for_active_markets(self._config['exchange']['pair_whitelist'])

    def filter_pairlist(self, pairlist: List[str], tickers: Dict) -> List[str]:
        """
        Filters and sorts pairlist and returns the whitelist again.
        Called on each bot iteration - please use internal caching if necessary
        :param pairlist: pairlist to filter or sort
        :param tickers: Tickers (from exchange.get_tickers()). May be cached.
        :return: new whitelist
        """
        return pairlist
