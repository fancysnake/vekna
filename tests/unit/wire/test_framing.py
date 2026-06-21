import asyncio

from vekna.wire import (
    CastGoodbye,
    GrimoireBegin,
    GrimoireEnd,
    WireMessage,
    decode_frame,
    encode_frame,
    read_frames,
)


def _drain(payload: bytes) -> list[WireMessage]:
    async def collect() -> list[WireMessage]:
        reader = asyncio.StreamReader()
        reader.feed_data(payload)
        reader.feed_eof()
        return [message async for message in read_frames(reader)]

    return asyncio.run(collect())


class TestFraming:
    @staticmethod
    def test_frame_is_single_newline_terminated_line():
        frame = encode_frame(GrimoireBegin(cast_id="c1"))

        assert frame.endswith(b"\n")
        assert frame.count(b"\n") == 1

    @staticmethod
    def test_decode_accepts_str_and_bytes():
        frame = encode_frame(GrimoireBegin(cast_id="c1"))

        assert decode_frame(frame) == decode_frame(frame.decode())


class TestReadFrames:
    @staticmethod
    def test_yields_each_message_in_order():
        messages: list[WireMessage] = [
            GrimoireBegin(cast_id="c1"),
            CastGoodbye(cast_id="c1", status="ok"),
            GrimoireEnd(cast_id="c1"),
        ]
        payload = b"".join(encode_frame(message) for message in messages)

        assert _drain(payload) == messages

    @staticmethod
    def test_skips_blank_lines():
        framed = encode_frame(GrimoireBegin(cast_id="c1"))

        result = _drain(b"\n" + framed + b"\n\n")

        assert len(result) == 1
        assert isinstance(result[0], GrimoireBegin)
