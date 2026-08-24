# -*- coding: utf-8 -*-
"""
向后兼容层：将 wikisource_parser 的接口平滑转发至 novel_parser。
"""
from novel_parser import resolve_book, BookNotFound, test_novel

__all__ = ["resolve_book", "BookNotFound", "test_novel"]
