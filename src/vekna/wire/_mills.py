from typing import Annotated

from pydantic import Discriminator, TypeAdapter

from ._pacts import WireMessage

_MESSAGE_ADAPTER: TypeAdapter[WireMessage] = TypeAdapter(
    Annotated[WireMessage, Discriminator("kind")]
)


def encode_frame(message: WireMessage) -> bytes:
    return _MESSAGE_ADAPTER.dump_json(message) + b"\n"


def decode_frame(frame: str | bytes) -> WireMessage:
    return _MESSAGE_ADAPTER.validate_json(frame)
