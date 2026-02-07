#!/usr/bin/env python3
"""
冗余分析脚本
用于分析News Coma项目中的冗余功能
"""

import ast
import os
import re
from collections import defaultdict
from typing import List, Dict, Set, Tuple
import yaml


class RedundancyAnalyzer:
    """冗余分析器"""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.src_dir = os.path.join(project_root, "src")
        self.tests_dir = os.path.join(project_root, "tests")
        self.config_path = os.path.join(project_root, "config.yaml")
        
        # 收集的数据
        self.imports = defaultdict(set)  # 文件 -> 导入模块
        self.functions = defaultdict(set)  # 文件 -> 函数名
        self.classes = defaultdict(set)  # 文件 -> 类名
        self.function_calls = defaultdict(set)  # 文件 -> 调用函数名
        self.class_uses = defaultdict(set)  # 文件 -> 使用类名
        
        # 解析结果
        self.used_functions = set()
        self.used_classes = set()
        self.dead_functions = []
        self.dead_classes = []
        self.unused_imports = []
        
    def analyze(self) -> Dict:
        """运行完整分析"""
        print("开始冗余分析...")
        
        # 1. 解析所有Python文件
        self._parse_all_python_files()
        
        # 2. 构建调用图
        self._build_call_graph()
        
        # 3. 识别死代码
        self._identify_dead_code()
        
        # 4. 检查配置使用
        config_issues = self._check_config_usage()
        
        # 5. 检查依赖使用
        dependency_issues = self._check_dependencies()
        
        # 6. 识别重复功能
        duplicate_issues = self._find_duplicate_functions()
        
        return {
            "dead_code": {
                "functions": self.dead_functions,
                "classes": self.dead_classes,
                "unused_imports": self.unused_imports
            },
            "config_issues": config_issues,
            "dependency_issues": dependency_issues,
            "duplicate_issues": duplicate_issues,
            "file_stats": self._get_file_stats()
        }
    
    def _parse_all_python_files(self):
        """解析所有Python文件"""
        for root, _, files in os.walk(self.project_root):
            for file in files:
                if file.endswith('.py'):
                    filepath = os.path.join(root, file)
                    self._parse_python_file(filepath)
    
    def _parse_python_file(self, filepath: str):
        """解析单个Python文件"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            # 提取导入
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        imports.add(name.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split('.')[0])
            
            # 提取函数定义
            functions = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions.add(node.name)
            
            # 提取类定义
            classes = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    classes.add(node.name)
            
            # 提取函数调用
            function_calls = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        function_calls.add(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        # 处理 obj.method() 形式
                        pass
            
            # 存储结果
            rel_path = os.path.relpath(filepath, self.project_root)
            self.imports[rel_path] = imports
            self.functions[rel_path] = functions
            self.classes[rel_path] = classes
            self.function_calls[rel_path] = function_calls
            
        except Exception as e:
            print(f"警告: 解析文件 {filepath} 失败: {e}")
    
    def _build_call_graph(self):
        """构建调用图"""
        # 标记main.py中的函数为入口点
        for filepath, funcs in self.functions.items():
            if filepath == "src/main.py":
                for func in funcs:
                    if func == "main":
                        self.used_functions.add(f"main.py:{func}")
        
        # 简单的调用跟踪
        for filepath, calls in self.function_calls.items():
            for call in calls:
                # 在定义中查找被调用的函数
                for func_file, funcs in self.functions.items():
                    if call in funcs:
                        self.used_functions.add(f"{func_file}:{call}")
        
        # 类的使用
        for filepath, uses in self.class_uses.items():
            for use in uses:
                for class_file, classes in self.classes.items():
                    if use in classes:
                        self.used_classes.add(f"{class_file}:{use}")
    
    def _identify_dead_code(self):
        """识别死代码"""
        # 查找未使用的函数
        for filepath, funcs in self.functions.items():
            for func in funcs:
                func_id = f"{filepath}:{func}"
                if func_id not in self.used_functions:
                    self.dead_functions.append({
                        "file": filepath,
                        "function": func,
                        "line": self._get_function_line(filepath, func)
                    })
        
        # 查找未使用的类
        for filepath, cls in self.classes.items():
            for cl in cls:
                class_id = f"{filepath}:{cl}"
                if class_id not in self.used_classes:
                    self.dead_classes.append({
                        "file": filepath,
                        "class": cl,
                        "line": self._get_class_line(filepath, cl)
                    })
        
        # 查找未使用的导入
        for filepath, imports in self.imports.items():
            used_in_file = set()
            # 收集文件中使用的符号
            for func in self.function_calls[filepath]:
                for imp in imports:
                    if func.startswith(imp):
                        used_in_file.add(imp)
            
            for imp in imports:
                if imp not in used_in_file:
                    self.unused_imports.append({
                        "file": filepath,
                        "import": imp
                    })
    
    def _check_config_usage(self) -> List[Dict]:
        """检查配置使用情况"""
        issues = []
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            # 检查use_smart_scorer
            use_smart_scorer = config.get('use_smart_scorer')
            if use_smart_scorer is not None:
                # 检查代码中是否有条件逻辑使用这个配置
                found_usage = False
                for root, _, files in os.walk(self.src_dir):
                    for file in files:
                        if file.endswith('.py'):
                            filepath = os.path.join(root, file)
                            with open(filepath, 'r', encoding='utf-8') as f:
                                content = f.read()
                                if 'use_smart_scorer' in content:
                                    found_usage = True
                                    break
                    
                    if found_usage:
                        break
                
                if not found_usage and use_smart_scorer is False:
                    issues.append({
                        "type": "unused_config",
                        "config": "use_smart_scorer",
                        "value": use_smart_scorer,
                        "issue": "配置设置为false，但代码中没有基于此的条件逻辑"
                    })
            
            # 检查retry_attempts和timeout是否被使用
            config_keys = ['retry_attempts', 'timeout']
            for key in config_keys:
                if key in config:
                    found = False
                    for root, _, files in os.walk(self.src_dir):
                        for file in files:
                            if file.endswith('.py'):
                                filepath = os.path.join(root, file)
                                with open(filepath, 'r', encoding='utf-8') as f:
                                    content = f.read()
                                    if key in content.lower().replace('_', ''):
                                        found = True
                                        break
                        
                        if found:
                            break
                    
                    if not found:
                        issues.append({
                            "type": "unused_config",
                            "config": key,
                            "value": config[key],
                            "issue": "配置项在代码中可能未被使用"
                        })
        
        except Exception as e:
            print(f"警告: 检查配置使用失败: {e}")
        
        return issues
    
    def _check_dependencies(self) -> List[Dict]:
        """检查依赖使用情况"""
        issues = []
        requirements_path = os.path.join(self.project_root, "requirements.txt")
        
        try:
            # 读取requirements.txt
            with open(requirements_path, 'r', encoding='utf-8') as f:
                requirements = f.read()
            
            # 提取包名
            packages = []
            for line in requirements.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    # 提取包名，如 "feedparser>=6.0.11" -> "feedparser"
                    match = re.match(r'([a-zA-Z0-9_-]+)', line)
                    if match:
                        packages.append(match.group(1).lower())
            
            # 检查导入使用
            all_imports = set()
            for imports in self.imports.values():
                all_imports.update(imports)
            
            for package in packages:
                if package not in all_imports:
                    issues.append({
                        "type": "unused_dependency",
                        "package": package,
                        "issue": "在requirements.txt中定义但可能未在代码中导入"
                    })
        
        except Exception as e:
            print(f"警告: 检查依赖失败: {e}")
        
        return issues
    
    def _find_duplicate_functions(self) -> List[Dict]:
        """查找重复功能"""
        issues = []
        
        # 简单查找：基于函数名和大致功能
        func_map = defaultdict(list)
        for filepath, funcs in self.functions.items():
            for func in funcs:
                func_map[func].append(filepath)
        
        for func, files in func_map.items():
            if len(files) > 1:
                issues.append({
                    "type": "duplicate_function",
                    "function": func,
                    "files": files,
                    "issue": f"相同函数名在多个文件中定义: {', '.join(files)}"
                })
        
        return issues
    
    def _get_function_line(self, filepath: str, func_name: str) -> int:
        """获取函数所在行号"""
        try:
            full_path = os.path.join(self.project_root, filepath)
            with open(full_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            for i, line in enumerate(lines, 1):
                if re.search(rf'def\s+{func_name}\s*\(', line):
                    return i
        except:
            pass
        return 0
    
    def _get_class_line(self, filepath: str, class_name: str) -> int:
        """获取类所在行号"""
        try:
            full_path = os.path.join(self.project_root, filepath)
            with open(full_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            for i, line in enumerate(lines, 1):
                if re.search(rf'class\s+{class_name}\s*\(', line):
                    return i
        except:
            pass
        return 0
    
    def _get_file_stats(self) -> Dict:
        """获取文件统计"""
        total_files = len(self.imports)
        total_functions = sum(len(funcs) for funcs in self.functions.values())
        total_classes = sum(len(cls) for cls in self.classes.values())
        
        return {
            "total_files": total_files,
            "total_functions": total_functions,
            "total_classes": total_classes,
            "dead_functions": len(self.dead_functions),
            "dead_classes": len(self.dead_classes),
            "unused_imports": len(self.unused_imports)
        }


def main():
    """主函数"""
    analyzer = RedundancyAnalyzer(".")
    results = analyzer.analyze()
    
    print("\n" + "="*70)
    print("冗余分析结果")
    print("="*70)
    
    # 1. 死代码报告
    dead_code = results["dead_code"]
    if dead_code["functions"]:
        print("\n[!] 未使用的函数:")
        for func in dead_code["functions"][:10]:  # 只显示前10个
            print(f"  {func['file']}:{func['line']} - {func['function']}()")
        if len(dead_code["functions"]) > 10:
            print(f"  ... 还有 {len(dead_code['functions']) - 10} 个未使用的函数")
    
    if dead_code["classes"]:
        print("\n[!] 未使用的类:")
        for cls in dead_code["classes"]:
            print(f"  {cls['file']}:{cls['line']} - class {cls['class']}")
    
    if dead_code["unused_imports"]:
        print("\n[!] 未使用的导入:")
        for imp in dead_code["unused_imports"]:
            print(f"  {imp['file']} - import {imp['import']}")
    
    # 2. 配置问题
    if results["config_issues"]:
        print("\n[!] 配置问题:")
        for issue in results["config_issues"]:
            print(f"  {issue['config']} = {issue['value']} - {issue['issue']}")
    
    # 3. 依赖问题
    if results["dependency_issues"]:
        print("\n[!] 依赖问题:")
        for issue in results["dependency_issues"]:
            print(f"  {issue['package']} - {issue['issue']}")
    
    # 4. 重复功能
    if results["duplicate_issues"]:
        print("\n[!] 重复功能:")
        for issue in results["duplicate_issues"]:
            print(f"  {issue['function']} - {issue['issue']}")
    
    # 5. 统计信息
    stats = results["file_stats"]
    print("\n代码库统计:")
    print(f"  总文件数: {stats['total_files']}")
    print(f"  总函数数: {stats['total_functions']}")
    print(f"  总类数: {stats['total_classes']}")
    print(f"  死函数比例: {stats['dead_functions']}/{stats['total_functions']} ({stats['dead_functions']/max(1, stats['total_functions'])*100:.1f}%)")
    print(f"  死类比例: {stats['dead_classes']}/{stats['total_classes']} ({stats['dead_classes']/max(1, stats['total_classes'])*100:.1f}%)")
    
    print("\n" + "="*70)
    print("建议:")
    
    # 基于分析提供建议
    if dead_code["functions"]:
        print("  1. 考虑移除未使用的函数以减少代码复杂度")
    
    if results["config_issues"]:
        print("  2. 检查并清理未使用的配置项")
    
    if results["dependency_issues"]:
        print("  3. 检查并移除未使用的依赖")
    
    if results["duplicate_issues"]:
        print("  4. 考虑重构重复的功能")
    
    print("="*70)


if __name__ == "__main__":
    main()