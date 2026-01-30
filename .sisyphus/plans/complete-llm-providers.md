# 完整AI提供商配置方案

## 支持的LLM提供商（14家）

### 🌍 国际提供商

| 提供商 | provider值 | 类型 | 推荐度 |
|--------|-----------|------|--------|
| **Gemini** | `gemini` | 免费/付费 | ⭐⭐⭐⭐⭐ |
| **OpenAI** | `openai` | 付费 | ⭐⭐⭐⭐ |
| **Azure OpenAI** | `azure` | 付费 | ⭐⭐⭐⭐ |
| **Anthropic Claude** | `claude` | 付费 | ⭐⭐⭐⭐ |

### 🇨🇳 国内提供商

| 提供商 | provider值 | 类型 | 推荐度 |
|--------|-----------|------|--------|
| **DeepSeek** | `deepseek` | 免费/付费 | ⭐⭐⭐⭐⭐ |
| **智谱GLM** | `zhipu` | 免费/付费 | ⭐⭐⭐⭐⭐ |
| **Kimi** | `kimi` | 付费 | ⭐⭐⭐⭐ |
| **通义千问** | `qwen` | 免费/付费 | ⭐⭐⭐⭐ |
| **百度文心** | `wenxin` | 付费 | ⭐⭐⭐ |
| **讯飞星火** | `spark` | 付费 | ⭐⭐⭐ |
| **零一万物** | `yi` | 免费/付费 | ⭐⭐⭐⭐ |
| **MiniMax** | `minimax` | 付费 | ⭐⭐⭐ |

### 🖥️ 本地部署

| 提供商 | provider值 | 类型 | 推荐度 |
|--------|-----------|------|--------|
| **Ollama** | `ollama` | 免费 | ⭐⭐⭐⭐ |

---

## 完整配置文件

```yaml
# ==========================================
# AI提供商配置
# 支持14家国内外LLM，一键切换
# ==========================================

# 当前使用的提供商（从下面列表中选择）
ai_provider: "deepseek"

# ==========================================
# 提供商配置列表
# ==========================================
ai_providers:
  
  # ==================== 国际提供商 ====================
  
  # 1. Gemini (Google) - 免费 generous
  gemini:
    enabled: true
    name: "Gemini 1.5 Flash"
    api_key: "${GEMINI_API_KEY}"
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
    model: "gemini-1.5-flash"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 15
    batch_size: 3
    max_concurrent: 2
    description: "Google免费模型，15 RPM"
  
  # 2. OpenAI - 付费
  openai:
    enabled: false
    name: "GPT-4o-mini"
    api_key: "${OPENAI_API_KEY}"
    base_url: "https://api.openai.com/v1"
    model: "gpt-4o-mini"
    max_tokens: 2000
    temperature: 0.3
    # rate_limit_rpm: 60  # 付费版可不限制
    batch_size: 5
    max_concurrent: 3
    description: "OpenAI官方，质量稳定"
  
  # 3. Azure OpenAI - 企业付费
  azure:
    enabled: false
    name: "Azure GPT-4"
    api_key: "${AZURE_OPENAI_API_KEY}"
    base_url: "https://{your-resource}.openai.azure.com/openai/deployments/{deployment}"
    api_version: "2024-02-15-preview"
    model: "gpt-4"
    max_tokens: 2000
    temperature: 0.3
    batch_size: 5
    max_concurrent: 3
    description: "Azure企业版，合规稳定"
  
  # 4. Claude (Anthropic) - 付费
  claude:
    enabled: false
    name: "Claude 3 Haiku"
    api_key: "${ANTHROPIC_API_KEY}"
    base_url: "https://api.anthropic.com/v1"
    model: "claude-3-haiku-20240307"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 50
    batch_size: 5
    max_concurrent: 3
    description: "Anthropic出品，推理能力强"
  
  # ==================== 国内提供商 ====================
  
  # 5. DeepSeek - 免费 generous 🥇
  deepseek:
    enabled: true
    name: "DeepSeek-V3"
    api_key: "${DEEPSEEK_API_KEY}"
    base_url: "https://api.deepseek.com/v1"
    model: "deepseek-chat"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 60
    batch_size: 5
    max_concurrent: 3
    description: "深度求索，中文强，免费60 RPM"
  
  # 6. 智谱GLM - 免费 generous 🥈
  zhipu:
    enabled: false
    name: "GLM-4-Flash"
    api_key: "${ZHIPU_API_KEY}"
    base_url: "https://open.bigmodel.cn/api/paas/v4"
    model: "glm-4-flash"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 100
    batch_size: 5
    max_concurrent: 3
    description: "清华出品，免费100 RPM"
  
  # 7. Kimi (Moonshot) 🥉
  kimi:
    enabled: false
    name: "Kimi k1.5"
    api_key: "${KIMI_API_KEY}"
    base_url: "https://api.moonshot.cn/v1"
    model: "moonshot-v1-8k"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 30
    batch_size: 3
    max_concurrent: 2
    description: "月之暗面，长文本王者"
  
  # 8. 通义千问 (阿里云)
  qwen:
    enabled: false
    name: "Qwen-Max"
    api_key: "${DASHSCOPE_API_KEY}"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: "qwen-max"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 60
    batch_size: 5
    max_concurrent: 3
    description: "阿里出品，多模态强"
  
  # 9. 百度文心
  wenxin:
    enabled: false
    name: "ERNIE-4.0"
    api_key: "${WENXIN_API_KEY}"
    secret_key: "${WENXIN_SECRET_KEY}"
    base_url: "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat"
    model: "completions_pro"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 60
    batch_size: 5
    max_concurrent: 3
    description: "百度文心，需适配"
  
  # 10. 讯飞星火
  spark:
    enabled: false
    name: "Spark-Max"
    app_id: "${SPARK_APPID}"
    api_key: "${SPARK_API_KEY}"
    api_secret: "${SPARK_API_SECRET}"
    base_url: "wss://spark-api.xf-yun.com/v3.5/chat"
    model: "generalv3.5"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 50
    batch_size: 5
    max_concurrent: 3
    description: "科大讯飞，WebSocket协议"
  
  # 11. 零一万物
  yi:
    enabled: false
    name: "Yi-Large"
    api_key: "${YI_API_KEY}"
    base_url: "https://api.lingyiwanwu.com/v1"
    model: "yi-large"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 60
    batch_size: 5
    max_concurrent: 3
    description: "李开复团队，中文强"
  
  # 12. MiniMax
  minimax:
    enabled: false
    name: "MiniMax-Text"
    api_key: "${MINIMAX_API_KEY}"
    group_id: "${MINIMAX_GROUP_ID}"
    base_url: "https://api.minimax.chat/v1"
    model: "abab6.5-chat"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 60
    batch_size: 5
    max_concurrent: 3
    description: "MiniMax，社交AI强"
  
  # ==================== 本地部署 ====================
  
  # 13. Ollama 本地模型
  ollama:
    enabled: false
    name: "Qwen2.5-14B"
    api_key: "ollama"  # 不需要真实key
    base_url: "http://localhost:11434/v1"
    model: "qwen2.5:14b"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 1000  # 本地无限制
    batch_size: 10
    max_concurrent: 5
    description: "本地部署，完全免费"

# ==========================================
# 全局评分配置（所有提供商共享）
# ==========================================
scoring_criteria:
  importance: 0.30      # 重要性
  timeliness: 0.20      # 时效性
  technical_depth: 0.20 # 技术深度
  audience_breadth: 0.15 # 受众广度
  practicality: 0.15    # 实用性

# ==========================================
# 系统配置
# ==========================================
retry_attempts: 3       # 失败重试次数
timeout: 120           # API调用超时（秒）

# 回退策略（当前提供商失败时自动切换）
fallback:
  enabled: true
  providers:            # 按优先级排序
    - "deepseek"
    - "zhipu"
    - "gemini"
    - "openai"
```

---

## 快速使用指南

### 1. 选择提供商

修改 `ai_provider` 字段：

```yaml
# 使用DeepSeek（推荐）
ai_provider: "deepseek"

# 使用智谱GLM
ai_provider: "zhipu"

# 使用Kimi
ai_provider: "kimi"

# 使用Gemini
ai_provider: "gemini"

# 使用OpenAI
ai_provider: "openai"
```

### 2. 设置API Key

根据选择的提供商，在GitHub Secrets中添加对应的环境变量：

| 提供商 | Secrets名称 | 获取地址 |
|--------|-------------|----------|
| Gemini | `GEMINI_API_KEY` | https://makersuite.google.com/app/apikey |
| OpenAI | `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| DeepSeek | `DEEPSEEK_API_KEY` | https://platform.deepseek.com/ |
| 智谱 | `ZHIPU_API_KEY` | https://open.bigmodel.cn/ |
| Kimi | `KIMI_API_KEY` | https://platform.moonshot.cn/ |
| Qwen | `DASHSCOPE_API_KEY` | https://dashscope.console.aliyun.com/ |

### 3. 一键切换脚本

```bash
#!/bin/bash
# switch-provider.sh

PROVIDER=$1

if [ -z "$PROVIDER" ]; then
    echo "Usage: ./switch-provider.sh <provider>"
    echo "Available providers:"
    echo "  International: gemini, openai, azure, claude"
    echo "  Domestic: deepseek, zhipu, kimi, qwen, wenxin, spark, yi, minimax"
    echo "  Local: ollama"
    exit 1
fi

# 修改ai_provider字段
sed -i "s/^ai_provider: .*/ai_provider: \"$PROVIDER\"/" config/config.yaml

echo "✅ 已切换到: $PROVIDER"
echo "请确保在GitHub Secrets中设置了对应的API Key"
```

**使用示例**:
```bash
./switch-provider.sh deepseek   # 切换到DeepSeek
./switch-provider.sh zhipu      # 切换到智谱GLM
./switch-provider.sh kimi       # 切换到Kimi
./switch-provider.sh gemini     # 切换到Gemini
```

---

## 提供商详细对比

### 免费额度对比

| 提供商 | 免费RPM | 免费Token/天 | 推荐指数 |
|--------|---------|--------------|----------|
| **智谱GLM** | 100 | generous | ⭐⭐⭐⭐⭐ |
| **DeepSeek** | 60 | generous | ⭐⭐⭐⭐⭐ |
| **Gemini** | 15 | 1M TPM | ⭐⭐⭐⭐ |
| **Kimi** | 30 | 有限 | ⭐⭐⭐⭐ |
| **Qwen** | 60 | 有限 | ⭐⭐⭐⭐ |

### 中文能力对比

| 提供商 | 中文理解 | 中文生成 | 技术术语 | 推荐指数 |
|--------|----------|----------|----------|----------|
| **DeepSeek** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **智谱GLM** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Kimi** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Qwen** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Gemini** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |

---

## 推荐方案

### 国内用户
```yaml
ai_provider: "deepseek"  # 首选

# 备选方案（自动回退）
fallback:
  enabled: true
  providers:
    - "deepseek"
    - "zhipu"      # DeepSeek失败时切换到智谱
    - "gemini"     # 智谱失败时切换到Gemini
```

### 海外用户
```yaml
ai_provider: "gemini"  # 首选

# 备选方案
fallback:
  enabled: true
  providers:
    - "gemini"
    - "openai"
    - "deepseek"
```

### 企业用户
```yaml
ai_provider: "azure"  # Azure OpenAI企业版

# 备选方案
fallback:
  enabled: true
  providers:
    - "azure"
    - "openai"
```

---

## 常见问题

### Q: 如何同时测试多个提供商？
```bash
# 测试DeepSeek
./switch-provider.sh deepseek
python src/main.py

# 测试智谱GLM
./switch-provider.sh zhipu
python src/main.py

# 对比结果
```

### Q: 某个提供商API失败了怎么办？
启用fallback自动回退：
```yaml
fallback:
  enabled: true
  providers:
    - "deepseek"
    - "zhipu"
    - "gemini"
```

### Q: 如何添加新的提供商？
1. 在 `ai_providers` 下添加新配置块
2. 设置 `provider: "新提供商标识"`
3. 配置 `base_url` 和 `model`
4. 在GitHub Actions中添加环境变量

---

## 完整14家提供商，一键切换，总有一款适合你！🎉
