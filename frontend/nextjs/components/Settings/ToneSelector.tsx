import React, { ChangeEvent } from 'react';

interface ToneSelectorProps {
  tone: string;
  onToneChange: (event: ChangeEvent<HTMLSelectElement>) => void;
}
export default function ToneSelector({ tone, onToneChange }: ToneSelectorProps) {
  return (
    <div className="form-group">
      <label htmlFor="tone" className="agent_question">语气 </label>
      <select
        name="tone"
        id="tone"
        value={tone}
        onChange={onToneChange}
        className="form-control-static"
        required
      >
        <option value="Objective">客观 — 公正、无偏见地呈现事实与发现</option>
        <option value="Formal">正式 — 符合学术规范，语言与结构严谨</option>
        <option value="Analytical">分析 — 批判性评估并详细审视数据与理论</option>
        <option value="Persuasive">说服 — 让读者接受特定观点或论据</option>
        <option value="Informative">信息型 — 就某一主题提供清晰、全面的信息</option>
        <option value="Explanatory">解释型 — 阐明复杂概念与过程</option>
        <option value="Descriptive">描述型 — 详细描绘现象、实验或案例</option>
        <option value="Critical">批判型 — 判断研究及其结论的有效性与相关性</option>
        <option value="Comparative">比较型 — 对比不同理论、数据或方法以突出异同</option>
        <option value="Speculative">推测型 — 探索假设、潜在影响或未来研究方向</option>
        <option value="Reflective">反思型 — 审视研究过程与个人洞见</option>
        <option value="Narrative">叙事型 — 用故事呈现研究发现或方法论</option>
        <option value="Humorous">幽默 — 轻松有趣，让内容更接地气</option>
        <option value="Optimistic">乐观 — 强调积极发现与潜在好处</option>
        <option value="Pessimistic">悲观 — 聚焦局限、挑战或负面结果</option>
        <option value="Simple">简明 — 面向年轻读者，用词基础、解释清楚</option>
        <option value="Casual">随意 — 对话式、轻松的口吻，适合日常阅读</option>
      </select>
    </div>
  );
}
