# News Coma - 智能新闻聚合系统

## 概述

News Coma 是一个智能新闻聚合系统，支持14家国内外LLM提供商，具备2-Pass评分系统，能够智能筛选和总结新闻。

## 核心特性

### 🚀 2-Pass 评分系统
- **差异化处理**：财经、科技、社会政治三大板块使用不同评分标准
- **宽松预筛 + 严格精选**：Pass 1 快速过滤，Pass 2 深度评分
- **固定比例输出**：40%财经 + 30%科技 + 30%社会政治

### 🔌 多提供商支持
- 支持14家LLM提供商：Gemini, OpenAI, Claude, DeepSeek, 智谱, Kimi, 通义千问等
- 自动回退机制：主提供商失败时自动切换到备用提供商
- 真批处理：一次API调用处理多条新闻，大幅降低API成本

### 📊 智能功能
- AI评分：基于5维度标准对新闻进行评分
- 自动翻译：英文新闻自动翻译为中文
- 智能总结：生成200字左右的中文总结
- 关键要点：提取3-5个关键要点
- 语义去重：TF-IDF轻量级语义去重

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置API密钥
编辑 `config/config.yaml`，设置AI提供商和API密钥：
```yaml
ai:
  ai_provider: "zhipu"  # 可选: gemini, openai, claude, deepseek, zhipu等
```

设置环境变量：
```bash
export ZHIPU_API_KEY="your-api-key"  # 根据选择的提供商设置
```

### 3. 运行系统
```bash
python src/main.py
```

## 2-Pass 系统配置

### 基本配置
```yaml
# config/config.yaml
ai:
  use_2pass: true  # 启用2-Pass评分系统
  
  # Pass 1 差异化阈值
  pass1_threshold_finance: 5.5  # 财经新闻阈值
  pass1_threshold_tech: 6.0     # 科技新闻阈值  
  pass1_threshold_politics: 5.5 # 社会政治新闻阈值
  
  # 板块配额
  category_quota_finance: 0.40  # 财经40%
  category_quota_tech: 0.30     # 科技30%
  category_quota_politics: 0.30 # 社会政治30%

output:
  max_news_count: 30  # 每期输出30条新闻
```

### 工作流程
1. **Pass 1**: 快速预筛，按板块差异化阈值过滤
2. **Pass 2**: 深度评分，AI进行完整5维度评估
3. **最终选取**: 按固定比例从各板块选取Top N新闻

## 项目结构

```
news-coma/
├── config/
│   └── config.yaml          # 主配置文件
├── src/
│   ├── main.py             # 主程序入口
│   ├── config.py           # 配置解析
│   ├── models.py           # 数据模型
│   ├── ai_scorer.py        # AI评分器（2-Pass核心）
│   ├── history_manager.py  # 历史记录和缓存
│   └── rss_parser.py       # RSS解析器
├── data/                   # 数据目录
├── docs/                   # 文档目录
│   └── 2pass-system.md     # 2-Pass系统详细文档
└── outputs/                # 输出文件
```

## 详细文档

- [2-Pass 评分系统详细文档](docs/2pass-system.md) - 系统架构、配置说明、技术实现

## 许可证

MIT License

