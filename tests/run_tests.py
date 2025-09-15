#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试运行脚本
运行所有测试或特定测试模块
"""

import sys
import os
import unittest

# 获取项目根目录（tests的父目录）
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_path = os.path.join(project_root, 'src')

# 添加src目录到Python路径
if src_path not in sys.path:
    sys.path.insert(0, src_path)

print(f"Python路径: {sys.path}")
print(f"项目根目录: {project_root}")
print(f"src目录: {src_path}")

def run_all_tests():
    """运行所有测试"""
    print("开始运行所有测试...")
    
    # 发现并运行所有测试
    loader = unittest.TestLoader()
    start_dir = os.path.dirname(__file__)
    suite = loader.discover(start_dir, pattern='test_*.py')
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()

def run_specific_test(test_module):
    """运行特定的测试模块"""
    print(f"开始运行测试模块: {test_module}")
    
    # 导入测试模块
    try:
        module = __import__(test_module)
    except ImportError as e:
        print(f"无法导入测试模块 {test_module}: {e}")
        return False
    
    # 运行测试
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(module)
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()

if __name__ == '__main__':
    if len(sys.argv) > 1:
        # 运行特定测试模块
        test_module = sys.argv[1]
        success = run_specific_test(test_module)
    else:
        # 运行所有测试
        success = run_all_tests()
    
    # 设置退出码
    sys.exit(0 if success else 1)
