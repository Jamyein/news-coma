# RSS新闻聚合项目架构设计

> 基于 GitHub Actions 的自动化 RSS 新闻聚合系统

## 📋 项目概述

- **目标**: 自动从多个 RSS 源获取新闻，使用 AI 评分筛选，生成 Markdown 文档和 RSS 订阅文件
- **执行环境**: GitHub Actions (每6小时自动运行)
- **技术栈**: Python 3.11+ + OpenAI API
- **输出**: Markdown 文档 + RSS feed.xml

---

## 🏗️ 完整目录结构

```
news/
├── .github/
│   └── workflows/
│       └── rss-aggregator.yml      # GitHub Actions 工作流配置
├── src/
│   ├── __init__.py
│   ├── config.py                   # 配置管理模块
│   ├── rss_fetcher.py              # RSS 获取模块
│   ├── ai_scorer.py                # AI 评分模块
│   ├── translator.py               # 翻译模块 (可合并到 ai_scorer)
│   ├── markdown_generator.py       # Markdown 生成模块
│   ├── rss_generator.py            # RSS 订阅文件生成模块
│   └── main.py                     # 主程序入口
├── config/
│   └── config.yaml                 # RSS源和AI配置
├── data/
│   └── history.json                # 历史数据(去重、统计)
├── docs/
│   └── latest.md                   # 最新新闻(始终更新)
├── archive/
│   └── YYYY-MM-DD.md               # 历史归档(按日期)
├── feed.xml                        # RSS订阅文件(根目录，URL稳定)
├── requirements.txt                # Python依赖
├── .gitignore                      # Git忽略配置
└── README.md                       # 项目说明
```

---

## 🔧 技术栈选择

### 核心依赖

| 依赖 | 用途 | 版本 |
|------|------|------|
| `feedparser` | RSS 解析 | >=6.0.11 |
| `python-dateutil` | 日期处理 | >=2.8.2 |
| `openai` | OpenAI API 客户端 | >=1.6.0 |
| `PyYAML` | YAML 配置解析 | >=6.0.1 |
| `requests` | HTTP 请求 | >=2.31.0 |
| `python-frontmatter` | Markdown frontmatter | >=1.0.0 |

### 选择理由

1. **feedparser**: 最成熟的 RSS 解析库，容错性强，支持各种 RSS/Atom 格式
2. **openai**: 官方 SDK，支持最新 API 格式，易于配置 base_url 切换兼容服务
3. **PyYAML**: 标准 YAML 解析，配置清晰易读
4. **requests**: 备用 HTTP 库，处理 feedparser 无法解析的特殊情况

---

## 📦 模块详细设计

### 1. 配置管理模块 (`src/config.py`)

**职责**: 加载和验证配置，提供全局配置访问

```python
# 接口设计
class Config:
    """配置管理类"""
    
    def __init__(self, config_path: str = "config/config.yaml"):
        """初始化配置"""
        pass
    
    @property
    def rss_sources(self) -> List[RSSSource]:
        """获取所有 RSS 源配置"""
        pass
    
    @property
    def ai_config(self) -> AIConfig:
        """获取 AI 配置"""
        pass
    
    @property
    def output_config(self) -> OutputConfig:
        """获取输出配置"""
        pass

# 数据模型
@dataclass
class RSSSource:
    name: str           # 源名称
    url: str            # RSS URL
    weight: float       # 权重 (影响排序)
    category: str       # 分类标签
    enabled: bool       # 是否启用

@dataclass
class AIConfig:
    api_key: str
    base_url: str       # 支持自定义 base_url 切换兼容服务
    model: str          # 默认: gpt-4o-mini
    max_tokens: int
    temperature: float
    scoring_criteria: Dict[str, float]  # 评分维度权重

@dataclass
class OutputConfig:
    max_news_count: int     # 输出新闻数量 (10)
    max_feed_items: int     # RSS feed 保留数量 (50)
    archive_days: int       # 归档保留天数
```

### 2. RSS 获取模块 (`src/rss_fetcher.py`)

**职责**: 从多个 RSS 源获取新闻，解析为标准格式

```python
# 接口设计
class RSSFetcher:
    """RSS 获取器"""
    
    def __init__(self, sources: List[RSSSource]):
        self.sources = sources
    
    def fetch_all(self) -> List[NewsItem]:
        """
        从所有源获取新闻
        
        流程:
        1. 遍历所有启用的 RSS 源
        2. 并行获取每个源的 feed
        3. 解析条目为标准 NewsItem 格式
        4. 去重 (基于 URL 或标题相似度)
        5. 返回统一列表
        
        Returns: 新闻条目列表 (按发布时间倒序)
        """
        pass
    
    def fetch_single(self, source: RSSSource) -> List[NewsItem]:
        """获取单个 RSS 源的新闻"""
        pass
    
    def _parse_entry(self, entry, source: RSSSource) -> NewsItem:
        """将 feedparser entry 解析为 NewsItem"""
        pass

@dataclass
class NewsItem:
    """标准化新闻条目"""
    id: str                    # 唯一标识 (URL hash 或 UUID)
    title: str                 # 原始标题
    link: str                  # 原文链接
    source: str                # 来源名称
    category: str              # 分类
    published_at: datetime     # 发布时间
    summary: str               # 原始摘要 (可选)
    content: str               # 原始内容 (可选)
    
    # AI 评分后填充
    ai_score: Optional[float] = None
    ai_summary: Optional[str] = None
    translated_title: Optional[str] = None
```

**关键实现细节**:
- 使用 `feedparser.parse()` 解析 RSS
- 错误处理: 单个源失败不影响其他源
- 并发: 使用 `concurrent.futures.ThreadPoolExecutor` 并行获取
- 去重策略: URL 精确匹配 + 标题相似度(Levenshtein距离)
- 时间窗口: 只获取最近 N 天的新闻(避免处理过期内容)

### 3. AI 评分模块 (`src/ai_scorer.py`)

**职责**: 使用 OpenAI API 对新闻进行评分、翻译和总结

```python
# 接口设计
class AIScorer:
    """AI 新闻评分器"""
    
    def __init__(self, config: AIConfig):
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url
        )
        self.model = config.model
        self.criteria = config.scoring_criteria
    
    def score_batch(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        批量评分新闻
        
        优化策略:
        - 每次处理 5-10 条(避免 token 超限)
        - 并行请求控制并发数
        - 失败重试机制(指数退避)
        
        Returns: 填充评分后的 NewsItem 列表
        """
        pass
    
    def score_single(self, item: NewsItem) -> NewsItem:
        """单条新闻评分"""
        prompt = self._build_prompt(item)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return self._parse_response(item, response)
    
    def _build_prompt(self, item: NewsItem) -> str:
        """构建评分 Prompt"""
        return f"""
        你是一位资深科技新闻编辑。请对以下新闻进行评分和分析。
        
        评分维度（1-10分制）：
        - 重要性 (30%): 行业影响、技术突破程度
        - 时效性 (20%): 新闻新鲜度
        - 技术深度 (20%): 技术相关性和专业深度
        - 受众广度 (15%): 影响范围和读者群体
        - 实用性 (15%): 对开发者的实际指导价值
        
        新闻信息：
        标题: {item.title}
        来源: {item.source}
        分类: {item.category}
        发布时间: {item.published_at}
        摘要: {item.summary or 'N/A'}
        
        请按以下 JSON 格式返回：
        {{
            "importance": 8,
            "timeliness": 9,
            "technical_depth": 7,
            "audience_breadth": 6,
            "practicality": 8,
            "total_score": 7.5,
            "chinese_title": "翻译成中文的标题",
            "chinese_summary": "200字左右的中文总结",
            "key_points": ["要点1", "要点2", "要点3"]
        }}
        """
    
    def _parse_response(self, item: NewsItem, response) -> NewsItem:
        """解析 AI 响应，填充 NewsItem"""
        pass
```

**评分算法**:
```
total_score = importance×0.3 + timeliness×0.2 + technical_depth×0.2 + audience_breadth×0.15 + practicality×0.15
```

### 4. Markdown 生成模块 (`src/markdown_generator.py`)

**职责**: 生成结构化 Markdown 文档

```python
# 接口设计
class MarkdownGenerator:
    """Markdown 生成器"""
    
    def __init__(self, output_dir: str = "docs"):
        self.output_dir = output_dir
        self.archive_dir = "archive"
    
    def generate(self, items: List[NewsItem], timestamp: datetime) -> Tuple[str, str]:
        """
        生成 Markdown 文件
        
        Returns:
            (latest_path, archive_path)
        """
        content = self._build_content(items, timestamp)
        
        # 更新 latest.md
        latest_path = os.path.join(self.output_dir, "latest.md")
        self._write_file(latest_path, content)
        
        # 创建归档
        archive_filename = timestamp.strftime("%Y-%m-%d") + ".md"
        archive_path = os.path.join(self.archive_dir, archive_filename)
        self._write_file(archive_path, content)
        
        return latest_path, archive_path
    
    def _build_content(self, items: List[NewsItem], timestamp: datetime) -> str:
        """构建 Markdown 内容"""
        header = f"""# 科技新闻精选

> 更新时间: {timestamp.strftime("%Y-%m-%d %H:%M UTC")}  
> 本期精选 {len(items)} 条高质量科技新闻

---

"""
        
        body = ""
        for i, item in enumerate(items, 1):
            body += f"""### {i}. {item.translated_title}

**来源**: {item.source} | **分类**: {item.category} | **评分**: {item.ai_score}/10

{item.ai_summary}

**关键要点**:
- {chr(10).join(['- ' + p for p in item.key_points])}

**原文链接**: [{item.title}]({item.link})

---

"""
        
        return header + body
```

**输出格式示例**:
```markdown
# 科技新闻精选

> 更新时间: 2026-01-30 12:00 UTC  
> 本期精选 10 条高质量科技新闻

---

### 1. OpenAI 发布 GPT-5 预览版

**来源**: TechCrunch | **分类**: AI | **评分**: 9.2/10

OpenAI 今日发布了 GPT-5 的预览版本，该模型在多模态理解和推理能力上有显著提升...

**关键要点**:
- 多模态能力大幅提升，支持视频理解
- 推理速度比 GPT-4 快 3 倍
- 定价保持不变，性价比更高

**原文链接**: [OpenAI Unveils GPT-5 Preview](https://techcrunch.com/...)

---

### 2. ...
```

### 5. RSS 订阅文件生成模块 (`src/rss_generator.py`)

**职责**: 生成 RSS feed.xml 文件

```python
# 接口设计
class RSSGenerator:
    """RSS 订阅文件生成器"""
    
    def __init__(self, feed_path: str = "feed.xml"):
        self.feed_path = feed_path
        self.max_items = 50  # 保留最近50条
    
    def generate(self, items: List[NewsItem], existing_items: List[Dict] = None) -> str:
        """
        生成 RSS feed.xml
        
        策略:
        1. 合并新旧条目(去重)
        2. 保留最近 N 条
        3. 生成标准 RSS 2.0 格式
        
        Args:
            items: 本次新生成的新闻
            existing_items: 从现有 feed.xml 解析的历史条目
        
        Returns: 生成的 RSS XML 字符串
        """
        pass
    
    def _merge_items(self, new_items: List[NewsItem], existing: List[Dict]) -> List[Dict]:
        """合并新旧条目，去重"""
        pass
    
    def _build_rss_xml(self, items: List[Dict]) -> str:
        """构建 RSS 2.0 XML"""
        rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
    <title>科技新闻精选</title>
    <link>https://github.com/{username}/{repo}</link>
    <description>由 AI 筛选的高质量科技新闻聚合</description>
    <language>zh-CN</language>
    <lastBuildDate>{format_rfc822(datetime.utcnow())}</lastBuildDate>
    <atom:link href="https://raw.githubusercontent.com/{username}/{repo}/main/feed.xml" rel="self" type="application/rss+xml" />
    {''.join([self._build_item_xml(item) for item in items])}
</channel>
</rss>"""
        return rss
    
    def _build_item_xml(self, item: Dict) -> str:
        """构建单个 item XML"""
        return f"""
    <item>
        <title>{escape_xml(item['title'])}</title>
        <link>{item['link']}</link>
        <description>{escape_xml(item['summary'])}</description>
        <pubDate>{format_rfc822(item['published_at'])}</pubDate>
        <guid isPermaLink="true">{item['link']}</guid>
        <category>{item['category']}</category>
    </item>"""
```

**Feed XML 示例**:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
    <title>科技新闻精选</title>
    <link>https://github.com/yourusername/news</link>
    <description>由 AI 筛选的高质量科技新闻聚合</description>
    <language>zh-CN</language>
    <lastBuildDate>Fri, 30 Jan 2026 12:00:00 GMT</lastBuildDate>
    <atom:link href="https://raw.githubusercontent.com/yourusername/news/main/feed.xml" rel="self" type="application/rss+xml" />
    <item>
        <title>OpenAI 发布 GPT-5 预览版</title>
        <link>https://techcrunch.com/...</link>
        <description>OpenAI 今日发布了 GPT-5 的预览版本...</description>
        <pubDate>Fri, 30 Jan 2026 10:00:00 GMT</pubDate>
        <guid isPermaLink="true">https://techcrunch.com/...</guid>
        <category>AI</category>
    </item>
    <!-- more items... -->
</channel>
</rss>
```

### 6. 历史数据管理 (`data/history.json`)

**职责**: 去重、统计、增量更新支持

```json
{
  "last_run": "2026-01-30T12:00:00Z",
  "processed_urls": [
    "https://techcrunch.com/...",
    "https://github.com/blog/..."
  ],
  "stats": {
    "total_runs": 150,
    "total_news_processed": 12500,
    "avg_news_per_run": 83
  },
  "source_stats": {
    "TechCrunch": {"fetched": 500, "selected": 45},
    "GitHub Blog": {"fetched": 300, "selected": 30}
  }
}
```

---

## 🔄 数据流转关系

```
┌─────────────────────────────────────────────────────────────────┐
│                        GitHub Actions Trigger                    │
│                    (每6小时 / 手动触发)                          │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Phase 1: 配置加载                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ config.yaml │→│  Config     │→│  RSS Sources + AI Config│  │
│  └─────────────┘  │  Manager    │  └─────────────────────────┘  │
│                   └─────────────┘                                │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼ (Parallel Wave 1)
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 2: RSS 获取 (并行)                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ Source 1 │ │ Source 2 │ │ Source 3 │ │  ...     │            │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘            │
│       │            │            │            │                  │
│       └────────────┴────────────┴────────────┘                  │
│                    ↓                                            │
│            ┌──────────────┐                                     │
│            │  去重合并     │                                     │
│            │  URL + 时间窗口│                                    │
│            └──────┬───────┘                                     │
│                   ↓                                             │
│            ┌──────────────┐                                     │
│            │ NewsItem[]   │                                     │
│            │ (候选池)      │                                    │
│            └──────────────┘                                     │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼ (Parallel Wave 2)
┌─────────────────────────────────────────────────────────────────┐
│                 Phase 3: AI 评分与翻译 (并行)                      │
│                                                                 │
│  批量处理(5-10条/批) → OpenAI API → 评分 + 翻译 + 总结            │
│                                                                 │
│  ┌──────────────────────────────────────────────┐              │
│  │  ScoredNewsItem[]                           │              │
│  │  - ai_score: 7.5                            │              │
│  │  - translated_title: "..."                  │              │
│  │  - chinese_summary: "..."                   │              │
│  │  - key_points: [...]                        │              │
│  └──────────────┬───────────────────────────────┘              │
│                 ↓                                               │
│            ┌──────────────┐                                     │
│            │  Top 10 排序  │                                     │
│            │  (按 ai_score)│                                    │
│            └──────┬───────┘                                     │
│                   ↓                                             │
│            ┌──────────────┐                                     │
│            │ Top10News[]  │                                     │
│            └──────────────┘                                     │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼ (Sequential - 需要顺序)
┌─────────────────────────────────────────────────────────────────┐
│                 Phase 4: 输出生成                                │
│                                                                 │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐    │
│  │                │  │                │  │                │    │
│  │  Markdown Gen  │  │  Archive Gen   │  │  RSS Feed Gen  │    │
│  │                │  │                │  │                │    │
│  │  docs/latest   │  │  archive/YYYY  │  │  feed.xml      │    │
│  │  .md           │  │  -MM-DD.md     │  │  (保留50条)     │   │
│  └────────┬───────┘  └────────┬───────┘  └────────┬───────┘    │
│           │                   │                   │            │
│           └───────────────────┼───────────────────┘            │
│                               ↓                                 │
│                       ┌──────────────┐                         │
│                       │   Git Commit │                         │
│                       │   & Push     │                         │
│                       └──────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## ⚙️ 配置文件示例 (`config/config.yaml`)

```yaml
# RSS 新闻聚合配置

# 数据源配置
rss_sources:
  - name: "TechCrunch"
    url: "https://techcrunch.com/feed/"
    weight: 1.0
    category: "科技"
    enabled: true
  
  - name: "GitHub Blog"
    url: "https://github.blog/feed/"
    weight: 1.2
    category: "开发"
    enabled: true
  
  - name: "Hacker News"
    url: "https://news.ycombinator.com/rss"
    weight: 1.5
    category: "技术"
    enabled: true
  
  - name: "Verge"
    url: "https://www.theverge.com/rss/index.xml"
    weight: 0.9
    category: "科技"
    enabled: true
  
  - name: "InfoQ"
    url: "https://feed.infoq.cn/"
    weight: 1.1
    category: "架构"
    enabled: true

# AI 配置
ai:
  # OpenAI 配置
  api_key: "${OPENAI_API_KEY}"  # 从环境变量读取
  base_url: "https://api.openai.com/v1"  # 可切换兼容服务
  model: "gpt-4o-mini"
  max_tokens: 2000
  temperature: 0.3
  
  # 评分维度权重 (总和应为 1.0)
  scoring_criteria:
    importance: 0.30      # 重要性
    timeliness: 0.20      # 时效性
    technical_depth: 0.20 # 技术深度
    audience_breadth: 0.15 # 受众广度
    practicality: 0.15    # 实用性
  
  # 批处理配置
  batch_size: 5           # 每批处理条数
  max_concurrent: 3       # 最大并发请求数
  retry_attempts: 3       # 失败重试次数

# 输出配置
output:
  max_news_count: 10      # 每期精选新闻数量
  max_feed_items: 50      # RSS feed 保留条数
  archive_days: 30        # 归档保留天数
  time_window_days: 7     # 只处理最近 N 天的新闻

# 过滤配置
filters:
  min_score_threshold: 6.0  # 最低评分阈值
  dedup_similarity: 0.85    # 标题相似度阈值(0-1)
  blocked_keywords:         # 屏蔽关键词列表
    - "广告"
    - "推广"
    - "促销"
```

---

## 🚀 GitHub Actions Workflow

### `.github/workflows/rss-aggregator.yml`

```yaml
name: RSS News Aggregator

on:
  # 每6小时运行一次 (UTC时间)
  schedule:
    - cron: '0 0,6,12,18 * * *'
  
  # 手动触发
  workflow_dispatch:
    inputs:
      debug_mode:
        description: 'Debug mode (保留临时文件)'
        required: false
        default: false
        type: boolean

# 权限配置 (最小权限原则)
permissions:
  contents: write  # 用于提交生成的文件
  actions: read    # 用于读取工作流信息

env:
  PYTHON_VERSION: '3.11'
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

jobs:
  aggregate:
    runs-on: ubuntu-latest
    
    steps:
      # 1. 检出代码
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # 获取完整历史用于归档
      
      # 2. 设置 Python 环境
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'
      
      # 3. 安装依赖
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      
      # 4. 运行主程序
      - name: Run RSS Aggregator
        id: aggregator
        run: |
          python src/main.py
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          DEBUG_MODE: ${{ github.event.inputs.debug_mode }}
      
      # 5. 提交生成的文件
      - name: Commit and push changes
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          
          # 检查是否有变更
          if [ -n "$(git status --porcelain)" ]; then
            git add docs/ archive/ feed.xml data/history.json
            git commit -m "📰 Update news aggregation [$(date -u +'%Y-%m-%d %H:%M UTC')]"
            git push
          else
            echo "No changes to commit"
          fi
      
      # 6. (可选) 创建 Release 作为长期备份
      - name: Create weekly release
        if: github.event.schedule == '0 0 * * 0'  # 每周日
        uses: softprops/action-gh-release@v1
        with:
          tag_name: archive-${{ github.run_id }}
          name: Weekly Archive ${{ github.run_id }}
          files: |
            archive/*.md
            feed.xml
          body: |
            Weekly archive of RSS news aggregation
            Generated at: ${{ github.event.head_commit.timestamp }}
```

---

## 📝 依赖列表 (`requirements.txt`)

```
# RSS 解析
feedparser>=6.0.11

# AI API
openai>=1.6.0

# 日期处理
python-dateutil>=2.8.2

# YAML 解析
PyYAML>=6.0.1

# HTTP 请求 (备用)
requests>=2.31.0

# Markdown frontmatter
python-frontmatter>=1.0.0

# 工具库
tenacity>=8.2.0      # 重试机制
python-dotenv>=1.0.0 # 环境变量
```

---

## 🔄 并行任务分解

### 执行波次规划

```
Wave 1 (完全并行 - I/O 密集型):
├── fetch_rss_source_1()      # ThreadPoolExecutor
├── fetch_rss_source_2()
├── fetch_rss_source_3()
└── ...

Wave 2 (并行但控制并发 - API 调用):
├── score_batch_1()           # 5-10条/批, 最大3并发
├── score_batch_2()
└── ...

Wave 3 (顺序执行 - 文件写入):
├── generate_markdown()       # 依赖 Wave 2 完成
├── generate_rss_feed()       # 依赖 Wave 2 完成
└── git_commit_and_push()     # 依赖 Wave 3 完成
```

### 依赖矩阵

| 任务 | 依赖 | 可并行 | 阻塞 |
|------|------|--------|------|
| 配置加载 | 无 | - | RSS 获取 |
| RSS 获取 | 配置 | Wave 1 (所有源) | AI 评分 |
| AI 评分 | RSS 获取 | Wave 2 (批处理) | Markdown/RSS 生成 |
| Markdown 生成 | AI 评分 | 否 | Git 提交 |
| RSS 生成 | AI 评分 | Markdown 生成 | Git 提交 |
| Git 提交 | Markdown + RSS | 否 | - |

### 性能优化建议

1. **RSS 获取**: 使用 `ThreadPoolExecutor(max_workers=5)`
   - 主要是网络 I/O，线程安全
   - 超时设置: 30 秒/源

2. **AI 评分**: 使用 `asyncio` + `Semaphore(3)`
   - OpenAI API 有速率限制
   - 批处理减少 API 调用次数
   - 指数退避重试

3. **错误隔离**:
   - 单个 RSS 源失败不影响其他源
   - 单条新闻评分失败可降级(跳过或使用默认值)

---

## 🔐 安全与最佳实践

### Secrets 配置

在 GitHub 仓库设置以下 Secrets:
- `OPENAI_API_KEY`: OpenAI API 密钥

### 权限最小化

- 仅申请 `contents: write` 权限
- API key 不存储在代码中
- 使用环境变量传递敏感信息

### 错误处理

1. **网络错误**: RSS 源超时/失败 → 跳过该源，记录日志
2. **API 错误**: OpenAI 调用失败 → 重试3次，仍失败则使用默认评分
3. **Git 错误**: 提交冲突 → 自动 rebase 或跳过本次提交

---

## 📊 监控与日志

### 日志级别

- **INFO**: 正常流程日志(开始/结束/统计)
- **WARNING**: 单个源失败、API 限流
- **ERROR**: 严重错误(无法继续执行)

### 统计输出

每次运行输出统计信息:
```
=== RSS 聚合统计 ===
运行时间: 2026-01-30 12:00:00 UTC
获取源数: 5/5 成功
获取条目: 120 条
去重后: 85 条
AI 评分: 85 条
最终输出: 10 条
耗时: 45.2 秒
==================
```

---

## 🚀 下一步行动

基于本架构设计，你需要完成以下工作:

1. **初始化项目**: 创建目录结构和基础文件
2. **配置 Secrets**: 在 GitHub 仓库添加 `OPENAI_API_KEY`
3. **调整 RSS 源**: 修改 `config/config.yaml` 中的 RSS 源
4. **测试运行**: 本地运行 `python src/main.py` 验证流程
5. **部署运行**: 推送代码到 GitHub，观察 Actions 执行

详细实现计划已准备好，请运行 `/start-work` 开始执行！
