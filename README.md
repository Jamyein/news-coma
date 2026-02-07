# News Coma - 智能 RSS 新闻聚合器

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/LLM-14%20Providers-green.svg" alt="14 LLM Providers">
  <img src="https://img.shields.io/badge/Schedule-GitHub%20Actions-orange.svg" alt="GitHub Actions">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License">
</p>

News Coma 是一个基于 Python 的智能 RSS 新闻聚合器，运行在 **GitHub Actions** 中每日自动运行。支持多家 LLM 提供商**，具备 AI 驱动的 **1-Pass** 评分系统，能够智能筛选、翻译、总结新闻并提取关键要点。

---

## 核心特性

### 🚀 1-Pass AI 评分系统
- **单次调用**：分类 + 评分 + 总结 一次 API 完成
- **并行批处理**：3 批次并行，120 秒超时保护
- **智能降级**：超时后自动单条处理

### LLM 提供商支持
- **自动回退**：主提供商失败自动切换备用
- **真批处理**：一次 API 处理多条新闻

### 📊 AI 智能功能
- **5 维度评分**：重要性(30%) + 时效性(20%) + 技术深度(20%) + 受众广度(15%) + 实用性(15%)
- **自动翻译**：英文新闻自动翻译中文
- **智能总结**：200 字中文摘要
- **关键要点**：提取 3-5 个核心要点
- **语义去重**：TF-IDF 轻量级去重

### ⚡ GitHub Actions 自动化
- **每日运行**：UTC 00:00 自动执行
- **零运维成本**：完全免费
- **手动触发**：支持 workflow_dispatch

---

## 快速开始

### 方案 1: GitHub Actions 自动化（推荐）

1. **Fork 仓库** 到你的 GitHub 账号

2. **配置 Secrets**
   ```
   Settings → Secrets → Actions → New repository secret
   
   Name: ZHIPU_API_KEY
   Value: your-api-key-here
   ```

3. **启用 Actions**
   ```
   Actions 页面 → "I understand my workflows, go ahead and enable them"
   ```

4. **完成！** 每天 UTC 00:00 自动运行

### 方案 2: 本地开发

```bash
# 1. 克隆仓库
git clone https://github.com/yourusername/news-coma.git
cd news-coma

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置
export ZHIPU_API_KEY="your-api-key"

# 4. 运行
python src/main.py
```

---

## 配置说明

### 基础配置 (`config/config.yaml`)

```yaml
smart_ai:
  # AI 提供商
  provider: "zhipu"  # gemini, openai, claude, deepseek, zhipu, kimi...
  
  # 提供商配置
  providers_config:
    zhipu:
      api_key: "${ZHIPU_API_KEY}"
      base_url: "https://open.bigmodel.cn/api/paas/v4"
      model: "glm-4-flash"
      max_tokens: 65536
      batch_size: 10
      max_concurrent: 3
  
  # 性能配置
  batch_size: 10              # 批次大小
  max_concurrent: 3           # 最大并发批次
  timeout_seconds: 90         # 超时时间
  max_output_items: 30        # 最大输出新闻数
  
  # 多样性权重
  diversity_weight: 0.3
  
  # 5维度评分权重
  scoring_criteria:
    importance: 0.30
    timeliness: 0.20
    technical_depth: 0.20
    audience_breadth: 0.15
    practicality: 0.15

# 启用 1-Pass
use_smart_scorer: true
```

---

## 项目结构

```
news-coma/
├── .github/workflows/           # GitHub Actions 工作流
│   └── rss-aggregator.yml
├── src/
│   ├── main.py                # 程序入口
│   ├── config.py              # 配置解析
│   ├── models.py              # 数据模型
│   ├── rss_fetcher.py         # RSS 获取
│   ├── SmartScorer/           # 1-Pass 评分系统
│   │   ├── smart_scorer.py    # 核心协调器
│   │   ├── batch_provider.py  # 批量 API 管理
│   │   ├── prompt_engine.py   # Prompt 生成
│   │   └── result_processor.py # 结果解析
│   ├── markdown_generator.py  # Markdown 输出
│   ├── rss_generator.py       # RSS 输出
│   └── history_manager.py     # 历史记录
├── requirements.txt           # 依赖
├── config.yaml            # 主配置文件
└── README.md                 # 本文件
```

---

## API Keys 配置

在 GitHub Secrets 中配置以下环境变量（根据你使用的提供商）：

```
# 国际提供商
GEMINI_API_KEY              # Google Gemini
OPENAI_API_KEY              # OpenAI
ANTHROPIC_API_KEY           # Claude
AZURE_OPENAI_API_KEY        # Azure OpenAI

# 国内提供商
ZHIPU_API_KEY               # 智谱 AI
DEEPSEEK_API_KEY            # DeepSeek
KIMI_API_KEY                # Moonshot Kimi
```

---

## 性能指标

基于典型运行（30-50 条新闻输入）：

| 指标 | 数值 |
|------|------|
| **总运行时间** | ~4 分钟 |
| **API 调用次数** | 3-6 次（批处理）|
| **代码行数** | ~750 行 |
| **内存占用** | <100 MB |
| **输出新闻数** | 30 条 |

---

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件
