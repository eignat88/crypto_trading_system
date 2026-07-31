import random
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class SlippageConfig:
    """Slippage configuration."""
    # Fixed slippage as percentage of price
    fixed_slippage: Decimal = Decimal("0.0005")  # 0.05%

    # Random slippage range (min, max) as percentage
    random_slippage_min: Decimal = Decimal("0")
    random_slippage_max: Decimal = Decimal("0.001")  # 0.1%

    # Volume-based slippage (additional slippage for large orders)
    volume_impact_threshold: Decimal = Decimal("0.01")  # 1% of average volume
    volume_impact_factor: Decimal = Decimal("0.1")  # 10% additional slippage per threshold


class SlippageModel:
    """Models price slippage for trades."""

    def __init__(
        self,
        config: SlippageConfig | None = None,
        seed: int | None = None,
    ) -> None:
        self.config = config or SlippageConfig()
        if seed is not None:
            random.seed(seed)

    def calculate_slippage(
        self,
        price: Decimal,
        quantity: Decimal,
        average_volume: Decimal | None = None,
        is_buy: bool = True,
    ) -> Decimal:
        """
        Calculate execution price with slippage.

        Args:
            price: Reference price (e.g., close price)
            quantity: Trade quantity
            average_volume: Average volume for volume-based slippage
            is_buy: True if buying (slippage increases price)

        Returns:
            Execution price with slippage applied
        """
        # Fixed slippage
        slippage = self.config.fixed_slippage

        # Random slippage
        if self.config.random_slippage_max > self.config.random_slippage_min:
            random_pct = Decimal(
                str(random.uniform(
                    float(self.config.random_slippage_min),
                    float(self.config.random_slippage_max),
                ))
            )
            slippage += random_pct

        # Volume-based slippage
        if average_volume and average_volume > 0:
            volume_ratio = quantity / average_volume
            if volume_ratio > self.config.volume_impact_threshold:
                excess_ratio = (
                    volume_ratio - self.config.volume_impact_threshold
                ) / self.config.volume_impact_threshold
                volume_impact = excess_ratio * self.config.volume_impact_factor
                slippage += volume_impact

        # Apply slippage
        if is_buy:
            # Buy: price increases
            execution_price = price * (Decimal("1") + slippage)
        else:
            # Sell: price decreases
            execution_price = price * (Decimal("1") - slippage)

        return execution_price

    def calculate_slippage_cost(
        self,
        reference_price: Decimal,
        execution_price: Decimal,
        quantity: Decimal,
    ) -> Decimal:
        """
        Calculate slippage cost.

        Args:
            reference_price: Original reference price
            execution_price: Actual execution price
            quantity: Trade quantity

        Returns:
            Slippage cost in quote currency
        """
        return abs(execution_price - reference_price) * quantity
