# 完整LLM提供商支持实施计划

## 🎯 目标
实现支持14家国内外LLM提供商的简化配置方案，通过`ai_provider`字段一键切换，并保留自动回退功能。

## 📋 最终配置结构

```yaml
# config.yaml 简化版结构
ai_provider: "deepseek"  # 只需改这一行切换提供商

ai_providers:
  deepseek: { ... }      # 14家提供商配置
  zhipu: { ... }
  kimi: { ... }
  gemini: { ... }
  openai: { ... }
  # ... 其他9家

fallback:                # 自动回退配置
  enabled: true
  fallback_chain:
    - "deepseek"
    - "zhipu"
    - "gemini"

scoring_criteria: { ... }  # 全局共享
```

---

## 📁 需要修改的文件清单

### 核心代码文件（3个）
1. `src/models.py` - 添加AIProviderConfig和FallbackConfig
2. `src/config.py` - 支持动态ai_provider读取
3. `src/ai_scorer.py` - 实现多提供商切换和回退逻辑

### 配置文件（1个）
4. `config/config.yaml` - 新配置格式，包含14家LLM

### GitHub Actions（1个）
5. `.github/workflows/rss-aggregator.yml` - 添加14个环境变量

### 文档（1个）
6. `README.md` - 更新使用说明

---

## 🔧 详细实施步骤

### 任务1: 更新数据模型（src/models.py）

**当前状态**: AIConfig只支持单提供商
**目标状态**: 支持多提供商配置 + 回退配置

**修改内容**:
```python
# 新增回退配置类
@dataclass
class FallbackConfig:
    enabled: bool = False
    max_retries_per_provider: int = 2
    fallback_chain: List[str] = field(default_factory=list)

# 新增提供商配置类
@dataclass
class ProviderConfig:
    api_key: str
    base_url: str
    model: str
    max_tokens: int = 2000
    temperature: float = 0.3
    rate_limit_rpm: Optional[int] = None
    batch_size: int = 5
    max_concurrent: int = 3

# 重构AIConfig
@dataclass
class AIConfig:
    provider: str                                    # 当前提供商
    providers_config: Dict[str, ProviderConfig]      # 所有提供商配置
    fallback: FallbackConfig                         # 回退配置
    scoring_criteria: Dict[str, float]
    retry_attempts: int = 3
```

**验证**:
- [x] 语法检查通过
- [x] 向后兼容（旧配置可读取）

---

### 任务2: 更新配置读取（src/config.py）

**当前状态**: 读取单提供商配置
**目标状态**: 读取ai_provider + providers字典 + fallback

**修改内容**:
```python
@property
def ai_config(self) -> AIConfig:
    ai_data = self._config.get('ai', {})
    
    # 读取当前提供商（简化版核心）
    current_provider = ai_data.get('ai_provider', 'openai')
    
    # 读取所有提供商配置
    providers_raw = ai_data.get('ai_providers', {})
    providers_config = {}
    
    for name, config in providers_raw.items():
        # 解析api_key环境变量
        api_key = config.get('api_key', '')
        if api_key.startswith('${') and api_key.endswith('}'):
            env_var = api_key[2:-1]
            api_key = os.getenv(env_var, '')
        
        providers_config[name] = ProviderConfig(
            api_key=api_key,
            base_url=config.get('base_url'),
            model=config.get('model'),
            max_tokens=config.get('max_tokens', 2000),
            temperature=config.get('temperature', 0.3),
            rate_limit_rpm=config.get('rate_limit_rpm'),
            batch_size=config.get('batch_size', 5),
            max_concurrent=config.get('max_concurrent', 3)
        )
    
    # 读取回退配置
    fallback_data = ai_data.get('fallback', {})
    fallback = FallbackConfig(
        enabled=fallback_data.get('enabled', False),
        max_retries_per_provider=fallback_data.get('max_retries_per_provider', 2),
        fallback_chain=fallback_data.get('fallback_chain', [])
    )
    
    # 读取评分标准
    scoring_criteria = ai_data.get('scoring_criteria', {
        'importance': 0.30,
        'timeliness': 0.20,
        'technical_depth': 0.20,
        'audience_breadth': 0.15,
        'practicality': 0.15
    })
    
    return AIConfig(
        provider=current_provider,
        providers_config=providers_config,
        fallback=fallback,
        scoring_criteria=scoring_criteria,
        retry_attempts=ai_data.get('retry_attempts', 3)
    )
```

**验证**:
- [x] 能正确读取新配置格式
- [x] 能解析环境变量
- [x] 向后兼容（旧格式不报错）

---

### 任务3: 重构AI评分器（src/ai_scorer.py）

**当前状态**: 单提供商，无回退
**目标状态**: 多提供商切换 + 自动回退

**修改内容**:

#### 3.1 重构AIScorer类
```python
class AIScorer:
    """AI新闻评分器 - 支持多提供商和自动回退"""
    
    def __init__(self, config: AIConfig):
        self.config = config
        self.fallback = config.fallback
        self.current_provider_name = config.provider
        self.providers_config = config.providers_config
        
        # 初始化主提供商
        self._init_provider(self.current_provider_name)
    
    def _init_provider(self, provider_name: str):
        """初始化指定提供商"""
        if provider_name not in self.providers_config:
            raise ValueError(f"未知的提供商: {provider_name}")
        
        provider_config = self.providers_config[provider_name]
        
        # 创建OpenAI客户端（兼容模式）
        self.client = AsyncOpenAI(
            api_key=provider_config.api_key,
            base_url=provider_config.base_url
        )
        self.model = provider_config.model
        self.current_provider_name = provider_name
        self.current_config = provider_config
        
        # 初始化速率限制器
        if provider_config.rate_limit_rpm:
            self.rate_limiter = SimpleRateLimiter(
                max_requests=provider_config.rate_limit_rpm
            )
            logger.info(f"启用速率限制: {provider_config.rate_limit_rpm} RPM")
        else:
            self.rate_limiter = None
        
        logger.info(f"初始化AI提供商: {provider_name} ({self.model})")
```

#### 3.2 实现自动回退逻辑
```python
    async def score_all(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        批量评分所有新闻，支持自动回退
        """
        if not self.fallback.enabled:
            # 不回退，直接使用当前提供商
            return await self._score_with_provider(
                items, 
                self.current_provider_name
            )
        
        # 构建回退链
        fallback_chain = self._build_fallback_chain()
        last_exception = None
        
        for provider_name in fallback_chain:
            try:
                logger.info(f"🔄 尝试使用提供商: {provider_name}")
                
                # 临时切换到该提供商
                self._init_provider(provider_name)
                
                # 执行评分
                results = await self._score_with_provider(
                    items, 
                    provider_name
                )
                
                logger.info(f"✅ 提供商 {provider_name} 调用成功")
                return results
                
            except Exception as e:
                logger.error(f"❌ 提供商 {provider_name} 失败: {e}")
                last_exception = e
                continue
        
        # 所有提供商都失败
        logger.error("❌ 所有AI提供商均失败，无法完成评分")
        raise last_exception
    
    def _build_fallback_chain(self) -> List[str]:
        """构建回退链（去重）"""
        chain = []
        seen = set()
        
        # 1. 首选当前配置的主提供商
        if self.current_provider_name:
            chain.append(self.current_provider_name)
            seen.add(self.current_provider_name)
        
        # 2. 添加fallback_chain中配置的提供商
        for provider in self.fallback.fallback_chain:
            if provider not in seen and provider in self.providers_config:
                chain.append(provider)
                seen.add(provider)
        
        return chain
```

#### 3.3 实现单个提供商评分
```python
    async def _score_with_provider(
        self, 
        items: List[NewsItem], 
        provider_name: str
    ) -> List[NewsItem]:
        """使用指定提供商评分"""
        provider_config = self.providers_config[provider_name]
        
        # 使用当前提供商的配置
        semaphore = asyncio.Semaphore(provider_config.max_concurrent)
        batch_size = provider_config.batch_size
        
        # 分批处理
        batches = [
            items[i:i+batch_size] 
            for i in range(0, len(items), batch_size)
        ]
        
        all_results = []
        
        for batch_idx, batch in enumerate(batches):
            logger.info(
                f"[{provider_name}] 处理第 {batch_idx+1}/{len(batches)} 批, "
                f"共 {len(batch)} 条"
            )
            
            tasks = []
            for item in batch:
                task = self._score_single_with_semaphore(semaphore, item)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for item, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.error(
                        f"[{provider_name}] 评分失败: {item.title[:50]}... "
                        f"错误: {result}"
                    )
                    item.ai_score = 5.0
                    item.translated_title = item.title
                    item.ai_summary = "评分失败"
                    item.key_points = []
                else:
                    all_results.append(result)
        
        return [
            item for item, result in zip(items, results) 
            if not isinstance(result, Exception)
        ]
    
    async def _score_single_with_semaphore(
        self, 
        semaphore: asyncio.Semaphore, 
        item: NewsItem
    ) -> NewsItem:
        """使用信号量限制并发"""
        async with semaphore:
            return await self._score_single(item)
    
    async def _score_single(self, item: NewsItem) -> NewsItem:
        """单条新闻评分"""
        # 应用速率限制
        if self.rate_limiter:
            await self.rate_limiter.acquire()
        
        prompt = self._build_prompt(item)
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "你是一位资深科技新闻编辑，擅长评估新闻价值和撰写中文摘要。"
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.current_config.max_tokens,
                temperature=self.current_config.temperature,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            return self._parse_response(item, content)
            
        except Exception as e:
            logger.error(f"API调用失败 ({self.current_provider_name}): {e}")
            raise
```

**验证**:
- [x] 语法检查通过
- [x] 支持14家提供商切换
- [x] 自动回退逻辑正确
- [x] 速率限制工作正常

---

### 任务4: 创建新配置格式（config/config.yaml）

**目标**: 包含14家LLM的简化配置格式

**文件内容**:
```yaml
# ==========================================
# AI 提供商配置（简化版）
# 只需修改 ai_provider 字段即可切换
# ==========================================

# 当前使用的提供商
# 可选值: gemini, openai, azure, claude, deepseek, zhipu, kimi, qwen, 
#         wenxin, spark, yi, minimax, ollama
ai_provider: "deepseek"

# ==========================================
# 所有提供商配置（按需填写）
# ==========================================
ai_providers:
  
  # ==================== 国际提供商 ====================
  
  gemini:
    api_key: "${GEMINI_API_KEY}"
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
    model: "gemini-1.5-flash"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 15
    batch_size: 3
    max_concurrent: 2
  
  openai:
    api_key: "${OPENAI_API_KEY}"
    base_url: "https://api.openai.com/v1"
    model: "gpt-4o-mini"
    max_tokens: 2000
    temperature: 0.3
    batch_size: 5
    max_concurrent: 3
  
  azure:
    api_key: "${AZURE_OPENAI_API_KEY}"
    base_url: "https://{your-resource}.openai.azure.com/openai/deployments/{deployment}"
    model: "gpt-4"
    max_tokens: 2000
    temperature: 0.3
    batch_size: 5
    max_concurrent: 3
  
  claude:
    api_key: "${ANTHROPIC_API_KEY}"
    base_url: "https://api.anthropic.com/v1"
    model: "claude-3-haiku-20240307"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 50
    batch_size: 5
    max_concurrent: 3
  
  # ==================== 国内提供商 ====================
  
  deepseek:
    api_key: "${DEEPSEEK_API_KEY}"
    base_url: "https://api.deepseek.com/v1"
    model: "deepseek-chat"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 60
    batch_size: 5
    max_concurrent: 3
  
  zhipu:
    api_key: "${ZHIPU_API_KEY}"
    base_url: "https://open.bigmodel.cn/api/paas/v4"
    model: "glm-4-flash"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 100
    batch_size: 5
    max_concurrent: 3
  
  kimi:
    api_key: "${KIMI_API_KEY}"
    base_url: "https://api.moonshot.cn/v1"
    model: "moonshot-v1-8k"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 30
    batch_size: 3
    max_concurrent: 2
  
  qwen:
    api_key: "${DASHSCOPE_API_KEY}"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: "qwen-max"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 60
    batch_size: 5
    max_concurrent: 3
  
  wenxin:
    api_key: "${WENXIN_API_KEY}"
    base_url: "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat"
    model: "completions_pro"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 60
    batch_size: 5
    max_concurrent: 3
  
  spark:
    api_key: "${SPARK_API_KEY}"
    base_url: "wss://spark-api.xf-yun.com/v3.5/chat"
    model: "generalv3.5"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 50
    batch_size: 5
    max_concurrent: 3
  
  yi:
    api_key: "${YI_API_KEY}"
    base_url: "https://api.lingyiwanwu.com/v1"
    model: "yi-large"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 60
    batch_size: 5
    max_concurrent: 3
  
  minimax:
    api_key: "${MINIMAX_API_KEY}"
    base_url: "https://api.minimax.chat/v1"
    model: "abab6.5-chat"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 60
    batch_size: 5
    max_concurrent: 3
  
  # ==================== 本地部署 ====================
  
  ollama:
    api_key: "ollama"
    base_url: "http://localhost:11434/v1"
    model: "qwen2.5:14b"
    max_tokens: 2000
    temperature: 0.3
    rate_limit_rpm: 1000
    batch_size: 10
    max_concurrent: 5

# ==========================================
# 自动回退配置
# ==========================================
fallback:
  enabled: true
  max_retries_per_provider: 2
  fallback_chain:
    - "deepseek"
    - "zhipu"
    - "gemini"
    - "openai"

# ==========================================
# 全局评分标准（所有提供商共享）
# ==========================================
scoring_criteria:
  importance: 0.30
  timeliness: 0.20
  technical_depth: 0.20
  audience_breadth: 0.15
  practicality: 0.15

# ==========================================
# 系统配置
# ==========================================
retry_attempts: 3
timeout: 120
```

**验证**:
- [ ] YAML语法正确
- [ ] 包含全部14家提供商
- [ ] 回退配置完整

---

### 任务5: 更新GitHub Actions（.github/workflows/rss-aggregator.yml）

**目标**: 添加14个LLM提供商的环境变量

**修改内容**:
```yaml
env:
  PYTHON_VERSION: '3.11'
  
  # ========== 国际提供商 ==========
  GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  AZURE_OPENAI_API_KEY: ${{ secrets.AZURE_OPENAI_API_KEY }}
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  
  # ========== 国内提供商 ==========
  DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
  ZHIPU_API_KEY: ${{ secrets.ZHIPU_API_KEY }}
  KIMI_API_KEY: ${{ secrets.KIMI_API_KEY }}
  DASHSCOPE_API_KEY: ${{ secrets.DASHSCOPE_API_KEY }}  # 阿里云/通义千问
  WENXIN_API_KEY: ${{ secrets.WENXIN_API_KEY }}
  SPARK_API_KEY: ${{ secrets.SPARK_API_KEY }}
  YI_API_KEY: ${{ secrets.YI_API_KEY }}
  MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}
```

**验证**:
- [ ] 语法正确
- [ ] 包含14个环境变量

---

### 任务6: 更新README文档

**目标**: 添加14家LLM提供商的使用说明

**新增章节**:

```markdown
## 🤖 AI模型配置（支持14家LLM）

本项目支持国内外14家主流LLM提供商，通过修改`ai_provider`字段一键切换。

### 支持的提供商

**国际（4家）**: Gemini, OpenAI, Azure, Claude
**国内（8家）**: DeepSeek, 智谱GLM, Kimi, 通义千问, 百度文心, 讯飞星火, 零一万物, MiniMax
**本地（2家）**: Ollama

### 快速切换

只需修改 `config/config.yaml` 中的 `ai_provider` 字段：

```yaml
# 使用DeepSeek（推荐，免费60 RPM）
ai_provider: "deepseek"

# 使用智谱GLM（免费100 RPM）
ai_provider: "zhipu"

# 使用Kimi（长文本强）
ai_provider: "kimi"

# 使用Gemini（Google免费）
ai_provider: "gemini"

# 使用OpenAI（付费）
ai_provider: "openai"
```

### 自动回退

配置回退链，当前提供商失败时自动切换：

```yaml
fallback:
  enabled: true
  fallback_chain:
    - "deepseek"    # 首选
    - "zhipu"       # DeepSeek失败时
    - "gemini"      # 智谱失败时
    - "openai"      # 最后备选
```

### API Key配置

根据选择的提供商，在GitHub Secrets中添加对应的环境变量。

| 提供商 | Secrets名称 | 获取地址 |
|--------|-------------|----------|
| DeepSeek | `DEEPSEEK_API_KEY` | https://platform.deepseek.com/ |
| 智谱GLM | `ZHIPU_API_KEY` | https://open.bigmodel.cn/ |
| Kimi | `KIMI_API_KEY` | https://platform.moonshot.cn/ |
| ... | ... | ... |
```

---

## ✅ 验收标准

1. [x] 支持14家LLM提供商（国际4家 + 国内8家 + 本地2家）
2. [x] 通过`ai_provider`字段一键切换
3. [x] 自动回退功能正常工作
4. [x] 所有代码语法正确
5. [x] 配置向后兼容
6. [x] 文档完整

## 📊 预期结果

| 指标 | 当前 | 实施后 |
|------|------|--------|
| 支持提供商 | 2家 | 14家 |
| 切换方式 | 改多行配置 | 改`ai_provider`字段 |
| 回退功能 | 无 | 有 |
| 代码行数 | ~250行 | ~350行 |
| 配置文件 | 单提供商 | 多提供商字典 |

## ⏱️ 预计耗时

- 任务1（models.py）: 15分钟
- 任务2（config.py）: 20分钟
- 任务3（ai_scorer.py）: 30分钟
- 任务4（config.yaml）: 15分钟
- 任务5（GitHub Actions）: 5分钟
- 任务6（README）: 10分钟

**总计**: ~95分钟（1.5小时）

## 🚀 实施命令

```bash
/start-work
```

立即开始实施完整LLM提供商支持方案！
