import React, { useState } from 'react';

export interface HotPlatform {
  code: string;
  name: string;
  source_type: 'dailyhotapi' | 'json_api';
  url?: string;
  items_path?: string;
  title_field?: string;
  hot_field?: string;
  url_field?: string;
  headers?: Record<string, string>;
  limit?: number;
}

const BUILTIN_PLATFORMS: HotPlatform[] = [
  { code: 'douyin', name: '抖音', source_type: 'dailyhotapi', limit: 50 },
  { code: 'toutiao', name: '今日头条', source_type: 'dailyhotapi', limit: 50 },
  { code: 'thepaper', name: '澎湃新闻', source_type: 'dailyhotapi', limit: 20 },
  { code: 'baidu', name: '百度', source_type: 'dailyhotapi', limit: 20 },
  { code: '36kr', name: '36氪', source_type: 'dailyhotapi', limit: 30 },
  { code: 'sspai', name: '少数派', source_type: 'dailyhotapi', limit: 20 },
  { code: 'v2ex', name: 'V2EX', source_type: 'dailyhotapi', limit: 20 },
  { code: 'juejin', name: '掘金', source_type: 'dailyhotapi', limit: 20 },
  { code: 'bilibili', name: 'B站', source_type: 'dailyhotapi', limit: 30 },
];

interface Props {
  hotPlatforms: HotPlatform[];
  onChange: (platforms: HotPlatform[]) => void;
}

const HotListPlatforms: React.FC<Props> = ({ hotPlatforms, onChange }) => {
  const [showForm, setShowForm] = useState(false);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [form, setForm] = useState<HotPlatform>({
    code: '',
    name: '',
    source_type: 'dailyhotapi',
    url: '',
    items_path: 'data',
    title_field: 'title',
    hot_field: 'hot',
    url_field: 'url',
    limit: 30,
  });

  const resetForm = () => {
    setForm({
      code: '', name: '', source_type: 'dailyhotapi', url: '',
      items_path: 'data', title_field: 'title', hot_field: 'hot',
      url_field: 'url', limit: 30,
    });
    setEditingIndex(null);
    setShowForm(false);
  };

  const handleAdd = () => {
    if (!form.code.trim() || !form.name.trim()) return;
    const newPlatforms = [...hotPlatforms];
    if (editingIndex !== null) {
      newPlatforms[editingIndex] = { ...form };
    } else {
      if (newPlatforms.some(p => p.code === form.code.trim())) return; // 重复
      newPlatforms.push({ ...form, code: form.code.trim() });
    }
    onChange(newPlatforms);
    resetForm();
  };

  const handleEdit = (index: number) => {
    setForm({ ...hotPlatforms[index] });
    setEditingIndex(index);
    setShowForm(true);
  };

  const handleDelete = (index: number) => {
    const newPlatforms = hotPlatforms.filter((_, i) => i !== index);
    onChange(newPlatforms);
  };

  const handleToggleBuiltin = (bp: HotPlatform) => {
    const exists = hotPlatforms.some(p => p.code === bp.code);
    if (exists) {
      onChange(hotPlatforms.filter(p => p.code !== bp.code));
    } else {
      onChange([...hotPlatforms, { ...bp }]);
    }
  };

  const customCount = hotPlatforms.filter(p => !BUILTIN_PLATFORMS.some(b => b.code === p.code)).length;

  return (
    <div className="form-group">
      <div className="settings hot-platforms-section">
        <div className="settings mcp-header">
          <label className="agent_question" style={{ margin: 0 }}>
            🔥 热榜平台管理
          </label>
          <button
            type="button"
            className="settings mcp-info-btn"
            onClick={() => setShowForm(!showForm)}
            title={showForm ? '收起表单' : '添加自定义平台'}
          >
            {showForm ? '✕' : '+'}
          </button>
        </div>
        <small className="text-muted" style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.82rem', display: 'block', marginBottom: '10px', lineHeight: '1.5' }}>
          勾选或添加平台后，<strong style={{ color: '#0d9488' }}>LLM 会根据你的查询内容智能选择调用哪些平台</strong>，数据被用作热榜报告的素材来源。
        </small>

        {/* 内置平台快捷开关 */}
        <div className="builtin-platforms" style={{ marginBottom: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <label className="agent_question" style={{ fontSize: '0.9rem', margin: 0 }}>内置平台</label>
            <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: '0.75rem' }}>
              已选 {hotPlatforms.filter(p => BUILTIN_PLATFORMS.some(b => b.code === p.code)).length}/{BUILTIN_PLATFORMS.length}
            </span>
          </div>
          <div className="platform-tags">
            {BUILTIN_PLATFORMS.map(bp => {
              const active = hotPlatforms.some(p => p.code === bp.code);
              return (
                <button
                  key={bp.code}
                  type="button"
                  className={`platform-tag ${active ? 'active' : ''}`}
                  onClick={() => handleToggleBuiltin(bp)}
                >
                  {bp.name}
                </button>
              );
            })}
          </div>
          <small className="text-muted" style={{ color: 'rgba(255,255,255,0.45)', fontSize: '0.75rem', marginTop: '6px', display: 'block' }}>
            点击切换启用/关闭，启用的平台会出现在热榜报告中
          </small>
        </div>

        {/* 已添加的自定义平台 */}
        {customCount > 0 && (
          <div className="custom-platforms" style={{ marginBottom: '12px' }}>
            <label className="agent_question" style={{ fontSize: '0.9rem', marginBottom: '6px' }}>自定义平台（{customCount}）</label>
            <div className="platform-list">
              {hotPlatforms.filter(p => !BUILTIN_PLATFORMS.some(b => b.code === p.code)).map((p, i) => {
                const realIndex = hotPlatforms.indexOf(p);
                return (
                  <div key={p.code} className="platform-item">
                    <span className="platform-item-name">{p.name}</span>
                    <span className="platform-item-source">{p.source_type === 'dailyhotapi' ? '每日热榜API' : '自定义API'}</span>
                    <button onClick={() => handleEdit(realIndex)} className="platform-item-btn">编辑</button>
                    <button onClick={() => handleDelete(realIndex)} className="platform-item-btn danger">删除</button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* 添加/编辑表单 */}
        {showForm && (
          <div className="platform-form">
            <div className="form-row">
              <div className="form-field">
                <label>平台代码 *</label>
                <input
                  type="text"
                  placeholder="英文标识，如 weibo、zhihu"
                  value={form.code}
                  onChange={e => setForm({ ...form, code: e.target.value.replace(/\s/g, '').toLowerCase() })}
                  disabled={editingIndex !== null}
                />
              </div>
              <div className="form-field">
                <label>平台名称 *</label>
                <input
                  type="text"
                  placeholder="中文显示名，如 微博、知乎"
                  value={form.name}
                  onChange={e => setForm({ ...form, name: e.target.value })}
                />
              </div>
              <div className="form-field">
                <label>数据源类型</label>
                <select
                  value={form.source_type}
                  onChange={e => setForm({ ...form, source_type: e.target.value as any })}
                >
                  <option value="dailyhotapi">每日热榜 API（通用）</option>
                  <option value="json_api">自定义 JSON API</option>
                </select>
              </div>
            </div>

            {form.source_type === 'json_api' && (
              <>
                <div className="form-field">
                  <label>API 地址</label>
                  <input
                    type="text"
                    placeholder="https://example.com/api/hot（返回 JSON 数据）"
                    value={form.url || ''}
                    onChange={e => setForm({ ...form, url: e.target.value })}
                  />
                </div>
                <div className="form-row">
                  <div className="form-field">
                    <label>条目路径</label>
                    <input type="text" placeholder="data" value={form.items_path || ''} onChange={e => setForm({ ...form, items_path: e.target.value })} />
                  </div>
                  <div className="form-field">
                    <label>标题字段</label>
                    <input type="text" placeholder="title" value={form.title_field || ''} onChange={e => setForm({ ...form, title_field: e.target.value })} />
                  </div>
                  <div className="form-field">
                    <label>热度字段</label>
                    <input type="text" placeholder="hot" value={form.hot_field || ''} onChange={e => setForm({ ...form, hot_field: e.target.value })} />
                  </div>
                </div>
                <div className="form-field">
                  <label>链接字段</label>
                  <input type="text" placeholder="url" value={form.url_field || ''} onChange={e => setForm({ ...form, url_field: e.target.value })} />
                </div>
                <div className="form-field">
                  <label>抓取数量上限</label>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={form.limit || 30}
                    onChange={e => setForm({ ...form, limit: parseInt(e.target.value) || 30 })}
                  />
                </div>
                <small className="text-muted" style={{ color: 'rgba(13,148,136,0.8)', fontSize: '0.75rem', display: 'block', marginBottom: '10px', lineHeight: '1.4' }}>
                  💡 自定义 API 需返回 JSON 格式，结构为 <code style={{ backgroundColor: 'rgba(255,255,255,0.1)', padding: '1px 3px', borderRadius: '3px' }}>{`{"data": [{"title": "...", "hot": "...", "url": "..."}]}`}</code>
                </small>
              </>
            )}

            <div className="form-actions">
              <button type="button" className="btn-primary" onClick={handleAdd}>
                {editingIndex !== null ? '保存修改' : '添加平台'}
              </button>
              <button type="button" className="btn-secondary" onClick={resetForm}>取消</button>
            </div>
          </div>
        )}

        {!showForm && customCount === 0 && (
          <button
            type="button"
            className="btn-add-custom"
            onClick={() => setShowForm(true)}
          >
            + 添加自定义平台（如微博、知乎等）
          </button>
        )}

        {!showForm && customCount > 0 && (
          <button
            type="button"
            className="btn-add-custom"
            onClick={() => setShowForm(true)}
            style={{ marginTop: '8px' }}
          >
            + 继续添加更多平台
          </button>
        )}
      </div>
    </div>
  );
};

export default HotListPlatforms;
