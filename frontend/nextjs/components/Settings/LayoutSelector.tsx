import React, { ChangeEvent } from 'react';

interface LayoutSelectorProps {
  layoutType: string;
  onLayoutChange: (event: ChangeEvent<HTMLSelectElement>) => void;
}

export default function LayoutSelector({ layoutType, onLayoutChange }: LayoutSelectorProps) {
  return (
    <div className="form-group">
      <label htmlFor="layoutType" className="agent_question">布局类型 </label>
      <select
        name="layoutType"
        id="layoutType"
        value={layoutType}
        onChange={onLayoutChange}
        className="form-control-static"
        required
      >
        <option value="research">研究 — 传统研究布局，展示详细结果</option>
        <option value="copilot">协作 — 研究报告与对话面板并排显示</option>
      </select>
    </div>
  );
} 