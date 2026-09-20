from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class QueueMessage:
    body: dict[str, Any]
    receipt_handle: str


class PayoutQueue:
    async def send(self, body: dict[str, Any]) -> None:
        raise NotImplementedError

    async def receive(self, max_messages: int = 1, wait_seconds: int = 20) -> list[QueueMessage]:
        raise NotImplementedError

    async def delete(self, receipt_handle: str) -> None:
        raise NotImplementedError


class InMemoryPayoutQueue(PayoutQueue):
    """Local/CI stand-in for SQS payout queue."""

    def __init__(self) -> None:
        self._messages: list[dict[str, Any]] = []
        self._next_handle = 1
        self._inflight: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def clear(self) -> None:
        self._messages.clear()
        self._inflight.clear()

    async def send(self, body: dict[str, Any]) -> None:
        async with self._lock:
            self._messages.append(dict(body))

    async def receive(self, max_messages: int = 1, wait_seconds: int = 20) -> list[QueueMessage]:
        del wait_seconds  # no long-poll in memory
        async with self._lock:
            out: list[QueueMessage] = []
            while self._messages and len(out) < max_messages:
                body = self._messages.pop(0)
                handle = str(self._next_handle)
                self._next_handle += 1
                self._inflight[handle] = body
                out.append(QueueMessage(body=body, receipt_handle=handle))
            return out

    async def delete(self, receipt_handle: str) -> None:
        async with self._lock:
            self._inflight.pop(receipt_handle, None)

    def pending_count(self) -> int:
        return len(self._messages)


class SqsPayoutQueue(PayoutQueue):
    def __init__(self, queue_url: str) -> None:
        import boto3

        self._url = queue_url
        self._client = boto3.client("sqs")

    async def send(self, body: dict[str, Any]) -> None:
        import json

        await asyncio.to_thread(
            self._client.send_message,
            QueueUrl=self._url,
            MessageBody=json.dumps(body),
        )

    async def receive(self, max_messages: int = 1, wait_seconds: int = 20) -> list[QueueMessage]:
        import json

        def _recv() -> list[QueueMessage]:
            resp = self._client.receive_message(
                QueueUrl=self._url,
                MaxNumberOfMessages=min(max_messages, 10),
                WaitTimeSeconds=wait_seconds,
                VisibilityTimeout=300,
            )
            out: list[QueueMessage] = []
            for msg in resp.get("Messages", []):
                out.append(
                    QueueMessage(
                        body=json.loads(msg["Body"]),
                        receipt_handle=msg["ReceiptHandle"],
                    )
                )
            return out

        return await asyncio.to_thread(_recv)

    async def delete(self, receipt_handle: str) -> None:
        await asyncio.to_thread(
            self._client.delete_message,
            QueueUrl=self._url,
            ReceiptHandle=receipt_handle,
        )


MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]
