# Gemini OpenAI Compatible Implementation - Decisions

## Date: 2026-01-30

### Architectural Decisions

#### Decision 1: Use OpenAI Compatible Mode vs Native SDK
**Options:**
1. Add `google-generativeai` dependency and use native SDK
2. Use OpenAI compatible endpoint with existing `openai` SDK

**Choice**: Option 2 - OpenAI compatible mode

**Rationale:**
- Zero new dependencies (keep dependency count at 5)
- Minimal code changes (~50 lines vs ~200 lines)
- Easier maintenance (one SDK to manage)
- Simple switching between providers (just change base_url)

**Trade-offs:**
- Slight delay in accessing newest Gemini features
- Dependent on Google's OpenAI compatibility layer

#### Decision 2: Inline Rate Limiter vs Separate Module
**Options:**
1. Create separate `src/rate_limiter.py` module
2. Inline SimpleRateLimiter in `ai_scorer.py`

**Choice**: Option 2 - Inline implementation

**Rationale:**
- Rate limiter is only used by AIScorer
- Keeps codebase minimal and focused
- Easier to understand (colocated with usage)
- Only ~40 lines of code

**Trade-offs:**
- Less reusable if other components need rate limiting
- Could extract later if needed

#### Decision 3: Configuration-Driven vs Code-Driven Provider Selection
**Options:**
1. Add `provider` field and branch logic in code
2. Use configuration (base_url, model) to determine provider

**Choice**: Option 2 - Configuration-driven

**Rationale:**
- No code changes needed to switch providers
- Same code path for both OpenAI and Gemini
- Cleaner abstraction (don't care which provider)
- Follows existing pattern in codebase

#### Decision 4: Optional Rate Limiting
**Options:**
1. Always enable rate limiting with default 60 RPM
2. Make it optional (None = disabled)

**Choice**: Option 2 - Optional with None default

**Rationale:**
- OpenAI paid tier doesn't need rate limiting
- Backward compatible with existing configs
- Explicit opt-in for rate limiting
- Clear intent when reading config

### Technical Decisions

#### Token Bucket vs Fixed Window Rate Limiting
**Choice**: Token bucket algorithm

**Rationale:**
- Allows burst requests (up to max_requests)
- Smooths out traffic over time
- More flexible than fixed window
- Industry standard approach

#### Asyncio Lock vs Semaphore for Rate Limiter
**Choice**: asyncio.Lock (per limiter instance)

**Rationale:**
- Rate limiter state must be synchronized
- Lock is released during sleep to allow concurrency
- Semaphore not needed (limiter is singleton per scorer)

### Configuration Decisions

#### Default Batch Size for Gemini
**Choice**: 3 (reduced from 5)

**Rationale:**
- 15 RPM / 2 concurrent = 7.5 batches per minute max
- Batch size 3 × 2 concurrent = 6 requests per batch cycle
- Well under 15 RPM limit even with retries

#### Timeout for Rate Limiter
**Choice**: 120 seconds (2 minutes)

**Rationale:**
- Long enough for queue to clear
- Short enough to fail fast if severely rate limited
- Matches typical API timeout expectations
