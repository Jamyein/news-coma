#!/usr/bin/env python3
"""
配置迁移工具 - 将旧的2-pass配置转换为1-pass简化配置

使用方法:
    python tools/config_migrator.py --input config.yaml --output config-1pass.yaml
    
或者直接在Python中使用:
    from tools.config_migrator import migrate_config
    new_config = migrate_config(old_config_dict)
"""

import argparse
import yaml
import sys
from typing import Dict, Any, Optional
from pathlib import Path


def migrate_provider_config(old_provider: Dict[str, Any]) -> Dict[str, Any]:
    """迁移单个提供商配置"""
    return {
        "api_key": old_provider.get("api_key", ""),
        "base_url": old_provider.get("base_url", ""),
        "model": old_provider.get("model", "glm-4-flash"),
        "max_tokens": old_provider.get("max_tokens", 4000),
        "temperature": old_provider.get("temperature", 0.3),
        "batch_size": old_provider.get("batch_size", 10),
        "max_concurrent": old_provider.get("max_concurrent", 3)
    }


def migrate_scoring_criteria(old_criteria: Optional[Dict[str, float]]) -> Dict[str, float]:
    """迁移评分标准"""
    if not old_criteria:
        return {
            "importance": 0.30,
            "timeliness": 0.20,
            "technical_depth": 0.20,
            "audience_breadth": 0.15,
            "practicality": 0.15
        }
    
    return {
        "importance": old_criteria.get("importance", 0.30),
        "timeliness": old_criteria.get("timeliness", 0.20),
        "technical_depth": old_criteria.get("technical_depth", 0.20),
        "audience_breadth": old_criteria.get("audience_breadth", 0.15),
        "practicality": old_criteria.get("practicality", 0.15)
    }


def migrate_config(old_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    将旧的2-pass配置转换为新的1-pass简化配置
    
    主要变更:
    - 移除所有2-pass相关配置
    - 简化提供商配置
    - 减少配置项从20+到8项
    """
    
    old_ai_config = old_config.get("ai", {})
    
    # 迁移提供商配置
    providers_config = {}
    old_providers = old_ai_config.get("ai_providers", {})
    for provider_name, provider_config in old_providers.items():
        providers_config[provider_name] = migrate_provider_config(provider_config)
    
    # 确定默认提供商
    default_provider = old_ai_config.get("ai_provider", "zhipu")
    
    # 迁移评分标准
    old_scoring_criteria = old_ai_config.get("scoring_criteria", {})
    scoring_criteria = migrate_scoring_criteria(old_scoring_criteria)
    
    # 构建新的1-pass配置（仅8项核心配置）
    new_config = {
        "smart_ai": {
            # 核心配置（2项）
            "provider": default_provider,
            "providers_config": providers_config,
            
            # 性能配置（4项）
            "batch_size": old_ai_config.get("true_batch_size", 10),
            "max_concurrent": old_ai_config.get("max_concurrent", 3),
            "timeout_seconds": old_ai_config.get("batch_timeout_seconds", 90),
            "max_output_items": old_ai_config.get("pass1_max_items", 30),
            
            # 筛选配置（1项）
            "diversity_weight": 0.3,
            
            # 评分标准
            "scoring_criteria": scoring_criteria,
            
            # 回退配置（简化）
            "fallback_enabled": True,
            "fallback_chain": ["deepseek", "gemini"]
        },
        
        # 保留其他不变的全局配置
        "rss_sources": old_config.get("rss_sources", []),
        "output": old_config.get("output", {}),
        "filters": old_config.get("filters", {}),
        "retry_attempts": old_config.get("retry_attempts", 3),
        "timeout": old_config.get("timeout", 120)
    }
    
    return new_config


def validate_config(config: Dict[str, Any]) -> bool:
    """验证1-pass配置是否有效"""
    smart_ai = config.get("smart_ai", {})
    
    # 检查必需字段
    required_fields = [
        "provider",
        "providers_config",
        "batch_size",
        "max_concurrent",
        "max_output_items"
    ]
    
    for field in required_fields:
        if field not in smart_ai:
            print(f"错误: 缺少必需字段 '{field}'")
            return False
    
    # 检查提供商配置
    provider = smart_ai["provider"]
    providers_config = smart_ai["providers_config"]
    
    if provider not in providers_config:
        print(f"错误: 默认提供商 '{provider}' 不在提供商配置中")
        return False
    
    # 检查提供商配置的必需字段
    provider_config = providers_config[provider]
    provider_required = ["api_key", "base_url", "model"]
    
    for field in provider_required:
        if field not in provider_config or not provider_config[field]:
            print(f"错误: 提供商 '{provider}' 缺少必需字段 '{field}'")
            return False
    
    print("✅ 配置验证通过")
    return True


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="配置迁移工具 - 将2-pass配置转换为1-pass配置",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 迁移单个配置文件
    python tools/config_migrator.py -i config.yaml -o config-1pass.yaml
    
    # 迁移并验证
    python tools/config_migrator.py -i config.yaml -o config-1pass.yaml --validate
    
    # 仅验证现有配置
    python tools/config_migrator.py -i config/config-1pass.yaml --validate-only
        """
    )
    
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="输入的2-pass配置文件路径"
    )
    
    parser.add_argument(
        "-o", "--output",
        help="输出的1-pass配置文件路径（如果不指定，则只验证）"
    )
    
    parser.add_argument(
        "--validate",
        action="store_true",
        help="迁移后验证新配置"
    )
    
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="仅验证现有1-pass配置，不进行迁移"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细的迁移过程"
    )
    
    args = parser.parse_args()
    
    # 仅验证模式
    if args.validate_only:
        print(f"🔍 验证配置: {args.input}")
        try:
            with open(args.input, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            if validate_config(config):
                print("✅ 配置验证通过")
                sys.exit(0)
            else:
                print("❌ 配置验证失败")
                sys.exit(1)
        except Exception as e:
            print(f"❌ 验证失败: {e}")
            sys.exit(1)
    
    # 迁移模式
    print(f"🚀 开始迁移配置")
    print(f"   输入: {args.input}")
    if args.output:
        print(f"   输出: {args.output}")
    
    try:
        # 读取旧配置
        with open(args.input, 'r', encoding='utf-8') as f:
            old_config = yaml.safe_load(f)
        
        if args.verbose:
            print(f"\n📋 旧配置概览:")
            print(f"   AI提供商: {old_config.get('ai', {}).get('ai_provider', 'N/A')}")
            print(f"   提供商数量: {len(old_config.get('ai', {}).get('ai_providers', {}))}")
            print(f"   RSS源数量: {len(old_config.get('rss_sources', []))}")
        
        # 执行迁移
        print(f"\n🔄 执行配置迁移...")
        new_config = migrate_config(old_config)
        
        # 验证新配置
        if args.validate or args.verbose:
            print(f"\n🔍 验证新配置...")
            if not validate_config(new_config):
                print("❌ 新配置验证失败")
                sys.exit(1)
        
        # 输出统计
        if args.verbose:
            print(f"\n📊 迁移统计:")
            old_ai = old_config.get('ai', {})
            new_ai = new_config.get('smart_ai', {})
            
            # 计算配置项数量
            old_config_count = len([k for k in old_ai.keys() if not k.startswith('_')])
            new_config_count = len([k for k in new_ai.keys() if not k.startswith('_')])
            
            print(f"   原配置项: ~{old_config_count} 项")
            print(f"   新配置项: {new_config_count} 项")
            print(f"   简化比例: {(1 - new_config_count/old_config_count)*100:.1f}%")
        
        # 保存新配置
        if args.output:
            print(f"\n💾 保存新配置到: {args.output}")
            
            # 确保目录存在
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(args.output, 'w', encoding='utf-8') as f:
                yaml.dump(new_config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            
            print("✅ 配置迁移完成!")
            
            # 输出下一步建议
            print(f"\n📖 下一步:")
            print(f"   1. 验证新配置: python tools/config_migrator.py -i {args.output} --validate-only")
            print(f"   2. 复制到配置目录: cp {args.output} config-1pass.yaml")
            print(f"   3. 测试运行: python src/main.py --config config-1pass.yaml")
        else:
            print("\n✅ 配置迁移验证完成!")
            print("   (使用 -o 参数指定输出文件以保存新配置)")
        
    except FileNotFoundError:
        print(f"❌ 错误: 找不到输入文件 '{args.input}'")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"❌ 错误: YAML解析失败 - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 错误: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
