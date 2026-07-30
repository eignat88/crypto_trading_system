from decimal import Decimal
from dataclasses import dataclass


@dataclass
class CommissionConfig:
    """Commission configuration."""
    maker_fee: Decimal = Decimal("0.001")  # 0.1%
    taker_fee: Decimal = Decimal("0.001")  # 0.1%
    minimum_fee: Decimal = Decimal("0.0001")  # Minimum fee in quote currency


class CommissionModel:
    """Calculates trading commissions."""

    def __init__(self, config: CommissionConfig = None):
        self.config = config or CommissionConfig()

    def calculate_commission(
        self,
        quantity: Decimal,
        price: Decimal,
        is_maker: bool = False,
    ) -> Decimal:
        """
        Calculate commission for a trade.

        Args:
            quantity: Trade quantity in base currency
            price: Trade price in quote currency
            is_maker: True if order is maker (limit order on book)

        Returns:
            Commission in quote currency
        """
        trade_value = quantity * price
        fee_rate = self.config.maker_fee if is_maker else self.config.taker_fee
        commission = trade_value * fee_rate

        # Apply minimum fee
        return max(commission, self.config.minimum_fee)

    def calculate_total_cost(
        self,
        quantity: Decimal,
        price: Decimal,
        is_maker: bool = False,
    ) -> Decimal:
        """
        Calculate total cost including commission.

        Args:
            quantity: Trade quantity in base currency
            price: Trade price in quote currency
            is_maker: True if order is maker

        Returns:
            Total cost in quote currency
        """
        trade_value = quantity * price
        commission = self.calculate_commission(quantity, price, is_maker)
        return trade_value + commission

    def calculate_net_proceeds(
        self,
        quantity: Decimal,
        price: Decimal,
        is_maker: bool = False,
    ) -> Decimal:
        """
        Calculate net proceeds after commission.

        Args:
            quantity: Trade quantity in base currency
            price: Trade price in quote currency
            is_maker: True if order is maker

        Returns:
            Net proceeds in quote currency
        """
        trade_value = quantity * price
        commission = self.calculate_commission(quantity, price, is_maker)
        return trade_value - commission
