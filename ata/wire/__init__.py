"""wire 协议解析内核（自 ava 移植，候选 1）。

parse_request/parse_response 是深接口：两个纯函数吸收 Anthropic/OpenAI
两族 wire 协议差异，异常自吞、零 IO。新增协议 = 在 protocol_facts 注册
一个 adapter；调用方不感知族数。
"""
from .parser import parse_request, parse_response

__all__ = ["parse_request", "parse_response"]
