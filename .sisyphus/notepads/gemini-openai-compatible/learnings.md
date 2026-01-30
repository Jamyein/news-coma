# Gemini OpenAI Compatible Implementation - Learnings

## Date: 2026-01-30
## Plan: gemini-openai-compatible

### Key Learnings

1. **OpenAI Compatible Mode is Powerful**
   - Gemini provides OpenAI-compatible endpoint: `https://generativelanguage.googleapis.com/v1beta/openai/`
   - Can use existing `openai` Python SDK without adding new dependencies
   - Same API calls, just different base_url and model name

2. **Rate Limiting is Essential for Free Tiers**
   - Gemini free tier: 15 RPM (requests per minute)
   - Without rate limiting, will hit 429 errors quickly
   - Implemented SimpleRateLimiter using token bucket algorithm
   - Key insight: Release lock while sleeping to allow other tasks to proceed

3. **Configuration-Driven Architecture**
   - Added `rate_limit_rpm` field to AIConfig (Optional[int])
   - When None: no rate limiting (for OpenAI paid tier)
   - When set: enables rate limiting (for Gemini free tier)
   - Allows easy switching between providers without code changes

4. **Batch Size Matters for Rate Limits**
   - Original: batch_size=5, max_concurrent=3 → could exceed 15 RPM
   - Adjusted for Gemini: batch_size=3, max_concurrent=2
   - Math: 3 × 2 = 6 requests/minute < 15 RPM limit ✓

5. **Environment Variable Flexibility**
   - Support both GEMINI_API_KEY and OPENAI_API_KEY
   - Config determines which one to use via api_key field
   - GitHub Actions workflow passes both, config selects

### Implementation Details

**Files Modified:**
1. `src/ai_scorer.py` - Added SimpleRateLimiter class (~40 lines)
2. `src/models.py` - Added rate_limit_rpm field to AIConfig
3. `src/config.py` - Read rate_limit_rpm from YAML config
4. `config/config.yaml` - Added Gemini configuration with comments
5. `.github/workflows/rss-aggregator.yml` - Added GEMINI_API_KEY env var
6. `README.md` - Updated documentation for dual-backend support

**Code Quality:**
- All Python files pass syntax check
- No new dependencies added (still 5 total)
- Backward compatible with OpenAI
- Clean separation of concerns

### Testing Notes

- Need to test with actual Gemini API key
- Monitor logs for "启用速率限制: 15 RPM" message
- Verify no 429 errors in production
- Check that rate limiting doesn't cause timeouts

### Future Improvements

1. Add adaptive rate limiting (reduce RPM on 429 errors)
2. Add metrics/logging for rate limiter statistics
3. Consider exponential backoff for retries
4. Add health check endpoint to verify API connectivity

### References

- Gemini OpenAI compatibility: https://ai.google.dev/gemini-api/docs/openai
- Token bucket algorithm: https://en.wikipedia.org/wiki/Token_bucket
- Python asyncio locks: https://docs.python.org/3/library/asyncio-sync.html
