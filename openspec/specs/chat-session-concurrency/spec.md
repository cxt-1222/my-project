# chat-session-concurrency Specification

## Purpose

让用户在同一个 AI 教练页面中并行使用多个独立聊天会话。每个会话各自接收问题、展示流式回答和来源，切换会话不会中断或串接其他会话的回答。

## Requirements

### Requirement: Different chat sessions can generate answers concurrently
系统 MUST 允许用户在一个聊天会话仍处于流式回答期间，切换到另一个不同的聊天会话并提交新问题。新请求 MUST 不得因另一个会话正在生成而被全局锁阻止、取消或放入隐式队列；两个会话的回答可以独立完成，完成顺序不要求与提交顺序一致。

#### Scenario: Submit a question in another session while the first answer streams
- **WHEN** 会话 A 正在接收流式回答，用户切换到会话 B 并提交问题
- **THEN** 会话 B 的请求被发送并开始独立生成，会话 A 的生成继续进行

#### Scenario: Switch between two in-progress sessions
- **WHEN** 会话 A 和会话 B 都在生成，用户在两者之间切换
- **THEN** 当前会话显示自己的增量回答和状态，另一个会话的生成不被清空、改写或显示到当前会话

#### Scenario: Answers finish in a different order than requests
- **WHEN** 会话 B 的模型回答先于会话 A 完成
- **THEN** B 的最终回答只保存到会话 B，A 的流仍可继续并最终保存到会话 A

### Requirement: Each session owns its stream state and sources
系统 MUST 按会话隔离每个流式请求的生成状态、增量文本、引用来源、完成结果和错误。会话切换或加载已保存历史 MUST NOT 覆盖该会话尚未完成的流式状态；一个会话的 SSE 事件、来源或错误 MUST NOT 修改另一个会话的消息。

#### Scenario: Load persisted history while that session is streaming
- **WHEN** 用户返回到仍在生成的会话，且页面触发已保存历史加载
- **THEN** 历史加载不得移除该会话当前请求及已接收的增量文本

#### Scenario: Keep source references with the matching answer
- **WHEN** 两个会话的 SSE 流返回不同的来源列表
- **THEN** 每份来源列表只显示并保存于对应会话的回答

### Requirement: Streamed deltas update the active answer without rebuilding chat history
系统 MUST 在收到流式增量时仅更新当前会话回答中的稳定文本节点，不得每收到一段 SSE 数据就重建回答气泡或整个聊天消息列表，也不得反复重启动画或平滑滚动。生成期间可暂时以纯文本展示增量，回答完成后再渲染 Markdown；会话切换、初次显示流式回答和回答完成时仍可执行完整渲染。增量更新不得重置用户已滚动离开底部的位置。

#### Scenario: Receive successive answer deltas
- **WHEN** 当前会话连续收到多个 SSE `delta` 事件
- **THEN** 既有聊天历史、流式回答行和文本节点保持稳定，仅文本节点内容随增量更新

#### Scenario: Read earlier content while a response continues
- **WHEN** 用户在回答生成期间滚动查看较早的聊天内容
- **THEN** 后续增量不得强制将聊天区域滚回底部

### Requirement: Unsent composer drafts belong to their session
系统 MUST 将尚未发送的输入草稿绑定到其所属会话。创建或切换到另一个会话时，新会话不得继承之前会话的草稿；返回原会话时应恢复其草稿。若用户尚未创建任何会话，则首个草稿在首次创建会话时归属到该会话。

#### Scenario: Create a new session while a draft is present
- **WHEN** 会话 A 的输入框中有未发送的问题，用户创建会话 B
- **THEN** 会话 B 的输入框为空，且该草稿只在会话 A 中保留

#### Scenario: Restore the draft after switching back
- **WHEN** 用户从会话 A 切换到会话 B，再切回 A
- **THEN** A 显示原草稿，B 不显示 A 的草稿

#### Scenario: Assign the first draft to the first created session
- **WHEN** 用户在尚无活动会话时输入草稿并创建首个会话
- **THEN** 该草稿归属首个会话，而不会成为其他新会话的草稿

### Requirement: A session has at most one in-flight answer
系统 MUST 允许不同会话并行，但同一会话在已有问答请求未完成时 MUST 拒绝再次提交，并清楚提示该会话仍在回答；该请求不得静默丢弃或自动排队。占用状态 MUST 在任何异步等待之前建立，以防快速重复提交或其他客户端造成同会话历史顺序竞争。

#### Scenario: Submit again in the same page session
- **WHEN** 同一页面中的会话已有未完成的流式请求，用户再次提交问题
- **THEN** 前端不发送第二个请求、不排队，并向用户说明当前对话正在生成

#### Scenario: Another client submits to the same in-flight session
- **WHEN** 另一个标签页或 API 客户端向已有活动请求的同一会话提交问题
- **THEN** 服务端立即拒绝该请求并返回明确冲突，不排队；其他 session_id 的请求仍可继续

#### Scenario: Submit in another session while one is locked
- **WHEN** 会话 A 正在回答且禁止再次提交
- **THEN** 会话 A 的限制不阻止会话 B 提交新问题

### Requirement: Stream lifecycle failures are isolated
系统 MUST 将单个会话流的完成、失败或取消限制在该会话内。一个流失败或超时 MUST NOT 清除其他会话的生成状态、禁用其他会话的输入或错误归属消息；用户退出登录或切换账号时，系统 MUST 取消当前页面中的流并忽略之后到达的旧账号事件。

#### Scenario: One stream fails while another is active
- **WHEN** 会话 A 的流失败而会话 B 仍在正常生成
- **THEN** A 显示自己的失败状态并释放 A 的提交限制，B 继续生成且不受影响

#### Scenario: Log out during active generation
- **WHEN** 用户在任一会话仍生成时退出登录或切换账号
- **THEN** 当前页面取消其活动流，迟到的响应不得写入新账号的聊天状态或本地存储

#### Scenario: Delete a session while it is generating
- **WHEN** 某会话仍有未完成的请求
- **THEN** 页面阻止删除该会话并说明需等待回答结束，避免请求完成后写入已删除会话

### Requirement: Concurrent chat preserves existing API compatibility
不同会话的并行问答 MUST 继续使用现有鉴权、SSE 问答端点和知识来源响应结构。系统 MUST 将模型服务商限流、超时或资源错误显示为对应会话的错误，而不得伪装成排队或其他会话的失败。

#### Scenario: Preserve existing SSE contract
- **WHEN** 用户在不同会话中同时提问
- **THEN** 每个请求仍使用现有流式问答契约，回答及来源能够按各自会话正确处理

#### Scenario: Provider refuses one concurrent request
- **WHEN** 模型服务商因并发额度或速率限制拒绝其中一个请求
- **THEN** 被拒绝的会话收到明确失败状态，其他已被接受的会话继续处理
