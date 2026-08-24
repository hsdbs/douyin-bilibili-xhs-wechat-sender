# -*- coding: utf-8 -*-
"""
向后兼容层：将 novel_parser 与 wikisource_parser 的接口转发至统一的 ebook_engine。
"""
from ebook_engine import resolve_book, BookNotFound, test_ebook_engine as test_novel

__all__ = ["resolve_book", "BookNotFound", "test_novel"]
