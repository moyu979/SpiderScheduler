import os
import sys

# 保证从任意目录运行 pytest 都能导入 src 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
