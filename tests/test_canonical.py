from typing import Any

from liquid_staking_basis.canonical import (
    CURVE_TOKEN_EXCHANGE,
    WITHDRAWAL_CLAIMED,
    WITHDRAWAL_REQUESTED,
    WITHDRAWALS_FINALIZED,
    decode_log,
)


def word(value: int) -> str:
    return f"{value:064x}"


def address_topic(value: str) -> str:
    return "0x" + "0" * 24 + value.removeprefix("0x").lower()


def test_decode_curve_token_exchange() -> None:
    log: dict[str, Any] = {
        "address": "0x828b154032950C8ff7CF8085D841723Db2696056",
        "topics": [CURVE_TOKEN_EXCHANGE, address_topic("0x" + "1" * 40)],
        "data": "0x" + word(0) + word(10**18) + word(1) + word(999 * 10**15),
    }

    category, row = decode_log(log)

    assert category == "curve_swap"
    assert row["sold_asset"] == "WETH"
    assert row["bought_asset"] == "stETH"
    assert row["tokens_sold"] == 1.0
    assert row["tokens_bought"] == 0.999


def test_decode_withdrawal_requested_and_claimed() -> None:
    queue = "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1"
    requested = {
        "address": queue,
        "topics": [
            WITHDRAWAL_REQUESTED,
            "0x" + word(7),
            address_topic("0x" + "2" * 40),
            address_topic("0x" + "3" * 40),
        ],
        "data": "0x" + word(2 * 10**18) + word(19 * 10**17),
    }
    claimed = {
        "address": queue,
        "topics": [
            WITHDRAWAL_CLAIMED,
            "0x" + word(7),
            address_topic("0x" + "3" * 40),
            address_topic("0x" + "4" * 40),
        ],
        "data": "0x" + word(2 * 10**18),
    }

    requested_category, requested_row = decode_log(requested)
    claimed_category, claimed_row = decode_log(claimed)

    assert requested_category == "withdrawal"
    assert requested_row["request_id"] == 7
    assert requested_row["amount_steth"] == 2.0
    assert claimed_category == "withdrawal"
    assert claimed_row["request_id"] == 7
    assert claimed_row["amount_eth"] == 2.0


def test_decode_withdrawals_finalized() -> None:
    log = {
        "address": "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1",
        "topics": [
            WITHDRAWALS_FINALIZED,
            "0x" + word(10),
            "0x" + word(20),
        ],
        "data": "0x" + word(5 * 10**18) + word(4 * 10**18) + word(1_700_000_000),
    }

    category, row = decode_log(log)

    assert category == "withdrawal"
    assert row["from_request_id"] == 10
    assert row["to_request_id"] == 20
    assert row["amount_eth_locked"] == 5.0
    assert row["finalization_timestamp"] == 1_700_000_000


