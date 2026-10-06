Unmodified copy of `skills/technical-analysis/src/` from the npm package
`@bitget-ai/bitget-signal@1.2.0` (MIT, Copyright (c) 2025 Bitget; LICENSE alongside).

sha256 at copy time (2026-10-06):
- kline_indicator_utils.py c6286fac9c1f6413236e862aab06014dfe9717fc91096b10d0c37bc0eee18da5
- kline_indicators.py      b19a5bc2a0c9b48d8cc5e3d94efc0330c95f15bec16cb34eece66fac501aff13

The skill imports these as top-level modules (`import kline_indicators`), so
engine/bitget_context.py puts this folder on sys.path before importing them.
