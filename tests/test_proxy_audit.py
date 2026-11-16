from liquid_staking_basis.proxy_audit import build_intervals, extract_transitions


def test_extracts_only_lido_base_namespace_transition() -> None:
    proxy = {
        "resolver": "aragon_implementation_call",
        "event_topic0": "0x" + "1" * 64,
        "namespace": "0x" + "2" * 64,
        "app_id": "0x" + "3" * 64,
    }
    implementation = "4" * 40
    logs = [
        {
            "blockNumber": "0x64",
            "logIndex": "0x0",
            "transactionHash": "0x" + "5" * 64,
            "topics": [proxy["event_topic0"], proxy["namespace"], proxy["app_id"]],
            "data": "0x" + "0" * 24 + implementation,
        },
        {
            "blockNumber": "0x65",
            "logIndex": "0x0",
            "transactionHash": "0x" + "6" * 64,
            "topics": [proxy["event_topic0"], "0x" + "9" * 64, proxy["app_id"]],
            "data": "0x" + "0" * 24 + "7" * 40,
        },
    ]
    transitions = extract_transitions(logs, proxy)
    assert len(transitions) == 1
    assert transitions[0]["implementation"] == "0x" + implementation


def test_builds_non_overlapping_implementation_intervals() -> None:
    transitions = [
        {
            "block_number": 200,
            "implementation": "0x" + "2" * 40,
            "transaction_hash": "0xabc",
            "log_index": 0,
            "evidence": "event",
        },
        {
            "block_number": 300,
            "implementation": "0x" + "3" * 40,
            "transaction_hash": "0xdef",
            "log_index": 0,
            "evidence": "event",
        },
    ]
    intervals = build_intervals(100, 400, "0x" + "1" * 40, transitions)
    assert [(item["start_block"], item["end_block"]) for item in intervals] == [
        (100, 199),
        (200, 299),
        (300, 400),
    ]
