"""Tests for the OSC listener."""
from __future__ import annotations

import pytest
from src.osc_listener import OSCListener


class TestOSCListener:
    def test_build_message_cue_fire(self):
        li = OSCListener()
        msg = li._build_message("/cue/7/go", 7, [])
        assert msg.type.value == "human_input"
        assert msg.payload["cue_number"] == 7
        assert msg.payload["osc_action"] == "fire"
        assert "cue_7" in msg.metadata.tags

    def test_build_message_cue_stop(self):
        li = OSCListener()
        msg = li._build_message("/cue/3/stop", 3, [])
        assert msg.payload["osc_action"] == "stop"

    def test_build_message_raw_osc(self):
        li = OSCListener()
        msg = li._build_message("/custom/addr", None, [1.0, 2.0])
        assert msg.type.value == "human_input"
        assert msg.payload["raw_address"] == "/custom/addr"
        assert msg.payload["args"] == [1.0, 2.0]

    def test_extract_cue_number(self):
        li = OSCListener()
        assert li._extract_cue_number("/cue/5/go") == 5
        assert li._extract_cue_number("/cue/12/pause") == 12
        assert li._extract_cue_number("/other") is None

    def test_parse_args_int_float(self):
        li = OSCListener()
        import struct
        data = b",if" + struct.pack(">i", 42) + struct.pack(">f", 3.14)
        args = li._parse_args(data, 0, 3)
        assert args == [42, pytest.approx(3.14)]

    def test_parse_args_string(self):
        li = OSCListener()
        # OSC string "hello" = 5 chars + null = 6, padded to 8 bytes
        # type_tag = ",s" (2) + null pad = 4 bytes total, at offset 0
        # args start at offset 4, padded to 8: "hello" + null + 2 nulls = 8 bytes
        osc_string = b"hello\x00\x00\x00"  # 8 bytes
        type_tag = b",s\x00\x00"  # 4 bytes (properly aligned)
        data = type_tag + osc_string  # 12 bytes total
        # args_offset: after the 4-byte type tag, the string starts at offset 4
        # string reader reads until null and pads to 4-byte boundary
        args = li._parse_args(data, 0, 4)  # type_offset=0, args_offset=4
        assert args == ["hello"]

    def test_parse_args_empty(self):
        li = OSCListener()
        args = li._parse_args(b"xxxx", 10, 20)  # invalid offsets
        assert args == []
