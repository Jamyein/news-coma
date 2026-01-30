# Gemini 3 Flash 适配实施计划

## 🎯 目标
将AI评分模块从OpenAI迁移到Google Gemini 3 Flash免费模型，并实现速率限制以符合免费版15 RPM限制。

## 📋 任务清单

### 任务1: 创建速率限制器模块
**文件**: `src/rate_limiter.py`
**描述**: 实现令牌桶算法，控制API调用频率
**优先级**: P0
**详细内容**:
```python
# 核心功能:
1. RateLimiter类 - 基础令牌桶限制器
   - __init__(max_requests=15, time_window=60)  # 15 RPM
   - acquire() - 异步获取令牌
   - 支持超时和等待

2. AdaptiveRateLimiter类 - 自适应限制器
   - 根据429错误自动降低RPM
   - 根据成功响应谨慎提高RPM
   - 范围: 5-60 RPM

3. 统计功能
   - 记录总请求数
   - 记录被限制次数
   - 记录总等待时间
```

### 任务2: 重构AI评分模块
**文件**: `src/ai_scorer.py`
**描述**: 支持OpenAI和Gemini双后端，默认使用Gemini
**优先级**: P0
**详细内容**:
```python
# 修改内容:
1. 添加Gemini支持
   - 导入google.generativeai as genai
   - 配置API key和模型
   - 适配Gemini的prompt格式

2. 集成速率限制器
   - 在__init__中初始化RateLimiter
   - 在_score_single中添加限制器调用
   - 支持并发控制（Semaphore + RateLimiter）

3. 处理Gemini响应差异
   - Gemini不原生支持JSON模式
   - 需要在prompt中要求JSON格式
   - 使用response_mime_type="application/json"

4. 错误处理增强
   - 捕获429错误并报告给限制器
   - 捕获其他API错误并降级
```

**Gemini配置示例**:
```python
import google.generativeai as genai

# 配置API
genai.configure(api_key=config.api_key)

# 创建模型实例
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config={
        "temperature": 0.3,
        "max_output_tokens": 2000,
        "response_mime_type": "application/json",
    }
)

# 调用（带速率限制）
async with rate_limiter:
    response = await model.generate_content_async(prompt)
```

### 任务3: 更新数据模型
**文件**: `src/models.py`
**描述**: 添加速率限制配置
**优先级**: P1
**详细内容**:
```python
@dataclass
class AIConfig:
    # 现有字段...
    provider: str = "gemini"  # "openai" 或 "gemini"
    rate_limit_rpm: int = 15  # RPM限制
    adaptive_rate_limit: bool = True  # 自适应调整
```

### 任务4: 更新配置文件
**文件**: `config/config.yaml`
**描述**: 添加Gemini配置示例
**优先级**: P1
**详细内容**:
```yaml
ai:
  # 提供商选择: openai 或 gemini
  provider: "gemini"
  
  # Gemini配置（免费版）
  gemini:
    api_key: "${GEMINI_API_KEY}"
    model: "gemini-1.5-flash"  # 免费版15 RPM
    # model: "gemini-1.5-flash-8b"  # 备选
    max_tokens: 2000
    temperature: 0.3
  
  # OpenAI配置（备选）
  openai:
    api_key: "${OPENAI_API_KEY}"
    base_url: "https://api.openai.com/v1"
    model: "gpt-4o-mini"
    max_tokens: 2000
    temperature: 0.3
  
  # 速率限制配置
  rate_limit:
    rpm: 15  # 每分钟最大请求数（Gemini免费版限制）
    adaptive: true  # 自适应调整
    max_wait_time: 120  # 最大等待秒数
  
  # 批处理配置（调整为符合RPM限制）
  batch_size: 3  # 减小批次（原5条）
  max_concurrent: 2  # 降低并发（原3）
  retry_attempts: 3
```

### 任务5: 更新依赖列表
**文件**: `requirements.txt`
**描述**: 添加Gemini SDK，保留OpenAI作为备选
**优先级**: P0
**详细内容**:
```txt
# AI API（双支持）
google-generativeai>=0.8.0  # Gemini支持
openai>=2.0.0,<3.0  # OpenAI备选

# 其他依赖保持不变
feedparser>=6.0.11,<7.0
python-dateutil>=2.8.2,<3.0
PyYAML>=6.0.1,<7.0
tenacity>=8.2.0,<9.0
```

### 任务6: 更新主程序
**文件**: `src/main.py`
**描述**: 支持Gemini API key环境变量
**优先级**: P1
**详细内容**:
```python
# 检查API key
if config.ai_config.provider == "gemini":
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        logger.error("❌ 环境变量 GEMINI_API_KEY 未设置")
        sys.exit(1)
else:
    api_key = os.getenv('OPENAI_API_KEY')
    # ...
```

### 任务7: 更新GitHub Actions
**文件**: `.github/workflows/rss-aggregator.yml`
**描述**: 添加Gemini API key支持
**优先级**: P1
**详细内容**:
```yaml
env:
  GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  # OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}  # 备选
```

## ⚠️ 关键考虑点

### Gemini免费版限制
- **15 RPM**: 每分钟最多15次请求
- **1500 RPD**: 每天最多1500次请求
- **1M TPM**: 每分钟最多1M tokens

### 批处理调整
原配置：batch_size=5, max_concurrent=3 → 理论15并发
新配置：batch_size=3, max_concurrent=2 → 理论6并发，符合15 RPM

### 降级策略
如果Gemini 429错误过多，自动切换回OpenAI（如果配置了）

## 📊 实施时间估算
- 任务1（速率限制器）: 30分钟
- 任务2（AI评分模块）: 45分钟
- 任务3-7（配置更新）: 30分钟
- **总计**: 约1.5-2小时

## ✅ 成功标准
1. 代码能使用Gemini API成功评分新闻
2. 不超过15 RPM限制（无429错误）
3. 评分质量和OpenAI版本相当
4. 支持配置切换回OpenAI
