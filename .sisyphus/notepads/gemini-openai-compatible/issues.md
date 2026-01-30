# Gemini OpenAI Compatible Implementation - Issues & Resolutions

## Date: 2026-01-30

### Issues Encountered

#### Issue 1: Rate Limiter Lock Contention
**Problem**: Initial rate limiter implementation held lock during sleep, blocking all other tasks.

**Solution**: Release lock before sleeping, re-acquire after:
```python
self.lock.release()
try:
    await asyncio.sleep(wait_time)
finally:
    await self.lock.acquire()
```

**Status**: ✅ Resolved

#### Issue 2: Environment Variable Name Confusion
**Problem**: Code uses `OPENAI_API_KEY` env var name but user might set `GEMINI_API_KEY`.

**Solution**: Support both in config.py:
```python
api_key = os.getenv('OPENAI_API_KEY') or os.getenv('GEMINI_API_KEY', '')
```

And in GitHub Actions workflow, pass both.

**Status**: ✅ Resolved

#### Issue 3: Batch Size vs Rate Limit
**Problem**: Original batch_size=5, max_concurrent=3 could exceed 15 RPM with retries.

**Solution**: Adjusted for Gemini:
- batch_size: 5 → 3
- max_concurrent: 3 → 2
- Theoretical max: 6 req/min < 15 RPM limit

**Status**: ✅ Resolved

#### Issue 4: Optional Field in Dataclass
**Problem**: Adding new field to AIConfig might break existing configs without the field.

**Solution**: Use Optional with default None:
```python
rate_limit_rpm: Optional[int] = None
```

This maintains backward compatibility.

**Status**: ✅ Resolved

### No Critical Blockers

All issues resolved during implementation. No remaining blockers.
