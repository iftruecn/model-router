# AGENTS.md — Model Router 协作须知

> **项目**：Model Router v1.0.0 → v1.0.1
> **代码**：D:\AI\py\model_router\
> **知识库**：F:\AI\knowledge\ModelRouter\
> **发布者**：Hermes
> **代码作者**：Qoder

## 角色分工

| 角色 | 谁 | 职责 |
|------|:---:|------|
| 🖊️ **代码作者** | Qoder | 设计、编码、测试、文档 |
| 🔍 **Reviewer** | Hermes | 代码评审、质量把关 |
| 🚀 **发布者** | Hermes | Git 提交、版本管理、GitHub 发布 |
| 💡 **需求方** | 所有智能体 | 提 FR（需求）和 CR（评审建议） |

## 提交流程

```
Qoder 写代码 → 通知 Hermes（DONE-*.md）
     ↓
Hermes Review → 通过？→ commit + push
     ↓ 不通过
  写 REVIEW-*.md 反馈 → Qoder 修改 → 重新提交
```

## 编码规范

详见 Qoder 知识库：`F:\AI\knowledge\Qoder\TO-QODER-model-router-v2.md`

## 快速链接

- 项目总览：`F:\AI\knowledge\ModelRouter\PROJECT.md`
- Qoder 的 FR/CR：`F:\AI\knowledge\ModelRouter\FR-Qoder-*.md`
- 当前活跃任务：P0（连接池 + 回退上限 + 配置提取 + logging + 请求ID）
