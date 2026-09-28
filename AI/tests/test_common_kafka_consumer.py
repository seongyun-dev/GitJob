from common.kafka import ConsumedMessage, KafkaPythonConsumer


def test_defer_rewinds_the_exact_uncommitted_record():
    class FakeConsumer:
        def __init__(self) -> None:
            self.seeks = []

        def seek(self, partition, offset) -> None:
            self.seeks.append((partition, offset))

    inner = FakeConsumer()
    transport = KafkaPythonConsumer(
        bootstrap_servers=("broker:9092",),
        topic="requests",
        group_id="analysis",
    )
    transport._consumer = inner
    message = ConsumedMessage(
        topic="requests",
        partition=3,
        offset=17,
        key=b"repo",
        value=b"{}",
    )

    transport.defer(message)

    partition, offset = inner.seeks[0]
    assert (partition.topic, partition.partition, offset) == ("requests", 3, 17)
