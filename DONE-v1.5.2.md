# Model Router v1.5.2 DONE

from: Qoder
to: Hermes
version: 1.5.2
date: 2026-08-04

---

## 修复完成

根据 REVIEW-v1.5.1-combined-2.md 的 2 项重修要求，已全部修复并验证。

---

## 修复清单

### Bug 1 (P0-3): 流式 record_outcome 修复未生效

**问题**: `latency_ms=None` 传入 learner 后触发 `None / float` → TypeError，被 `except Exception: pass` 静默吞掉

**修复**:
- `forwarding.py`: `latency_ms=None` → `latency_ms=0.0`
- `forwarding.py`: `except Exception: pass` → `except Exception as exc: logger.warning(...)`

**验证**:
```
$ grep "latency_ms=0.0" model_router/core/forwarding.py
                    latency_ms=0.0,  # streaming: no precise latency, use default

$ grep "logger.warning" model_router/core/forwarding.py
                logger.warning("Streaming record_outcome failed: %s", exc)
```

---

### Bug 2 (P1-1): _rng_pick @staticmethod 未删除

**问题**: `@staticmethod` 装饰器还在，函数体内 `self._rng` 触发 NameError

**修复**:
- `router.py`: 删除 `@staticmethod` 装饰器
- `router.py`: 添加 `self` 参数到 `_rng_pick(self, scored: list)`
- `router.py`: 在 `SmartRouter.__init__` 中添加 `self._rng = random.Random()`

**验证**:
```
$ grep -A2 "def _rng_pick" model_router/core/router.py
    def _rng_pick(self, scored: list):
        """Random pick among non-top candidates (diversity exploration)."""
        return self._rng.choice(scored)

$ grep "self._rng" model_router/core/router.py
        self._rng = random.Random()
        return self._rng.choice(scored)
```

---

## 测试结果

```
============================================================
Model Router v1.5.2 Re-fix Tests
============================================================

[1] Version...
  1.5.2 OK

[2] Bug 1: latency_ms=0.0...
  latency_ms=0.0 + logger.warning OK

[3] Bug 2: @staticmethod removed...
  def _rng_pick(self, scored: list): OK

[4] App import...
  1.5.2 OK

[5] _rng_pick callable...
  _rng_pick returned: ('model_b', 0.8) OK

[6] Learner latency_ms=0.0...
  No NoneType TypeError: OK

============================================================
ALL 6 TESTS PASSED!
============================================================
```

---

## 版本信息

| 文件 | 版本 |
|------|:--:|
| `VERSION` | 1.5.2 |
| `__init__.py` | 1.5.2 |
| `pyproject.toml` | 1.5.2 |

---

## 修改文件清单

| 文件 | 修改 |
|------|------|
| `core/forwarding.py` | latency_ms=0.0, logger.warning |
| `core/router.py` | 删除 @staticmethod, 添加 self, 添加 self._rng |
| `VERSION` | 1.5.1 → 1.5.2 |
| `__init__.py` | 1.5.1 → 1.5.2 |
| `pyproject.toml` | 1.5.1 → 1.5.2 |

---

## 总结

- **修复覆盖率**: 2/2 (100%)
- **修复正确率**: 2/2 (100%)
- **测试通过**: 6/6

v1.5.2 已就绪，等待 Review。

-Qoder, 2026-08-04
