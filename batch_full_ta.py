#!/usr/bin/env python3
"""兼容旧命令：统一走只执行数据、RSI 与技术分析的批处理入口。"""
import os
import subprocess
import sys


if __name__ == '__main__':
    root = os.path.dirname(os.path.abspath(__file__))
    raise SystemExit(subprocess.call(
        [sys.executable, os.path.join(root, 'update_all.py'), '--no-open', *sys.argv[1:]],
        cwd=root,
    ))
