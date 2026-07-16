import React, { useState, useEffect } from 'react';
import HotListPlatforms, { HotPlatform } from './HotListPlatforms';

interface MCPConfig {
  name: string;
  command: string;
  args: string[];
  env: Record<string, string>;
}

interface MCPSelectorProps {
  mcpEnabled: boolean;
  mcpConfigs: MCPConfig[];
  onMCPChange: (enabled: boolean, configs: MCPConfig[]) => void;
  hotPlatforms?: HotPlatform[];
  onHotPlatformsChange?: (platforms: HotPlatform[]) => void;
}

const MCPSelector: React.FC<MCPSelectorProps> = ({
  mcpEnabled,
  mcpConfigs,
  onMCPChange,
  hotPlatforms = [],
  onHotPlatformsChange,
}) => {
  const [enabled, setEnabled] = useState(mcpEnabled);
  const [configText, setConfigText] = useState(() => {
    // Initialize with the passed configs, handling empty array case
    if (Array.isArray(mcpConfigs) && mcpConfigs.length > 0) {
      return JSON.stringify(mcpConfigs, null, 2);
    }
    return '[]';
  });
  const [validationStatus, setValidationStatus] = useState<{
    isValid: boolean;
    message: string;
    serverCount?: number;
  }>({ isValid: true, message: '✓ JSON 格式正确' });
  const [showInfoModal, setShowInfoModal] = useState(false);

  useEffect(() => {
    validateConfig(configText);
  }, [configText]);

  // Sync with props when they change (for localStorage loading)
  useEffect(() => {
    setEnabled(mcpEnabled);
  }, [mcpEnabled]);

  useEffect(() => {
    if (Array.isArray(mcpConfigs)) {
      const newConfigText = mcpConfigs.length > 0 ? JSON.stringify(mcpConfigs, null, 2) : '[]';
      setConfigText(newConfigText);
    }
  }, [mcpConfigs]);

  const validateConfig = (text: string) => {
    if (!text.trim() || text.trim() === '[]') {
      setValidationStatus({ isValid: true, message: '（空配置）' });
      return true;
    }

    try {
      const parsed = JSON.parse(text);

      if (!Array.isArray(parsed)) {
        throw new Error('配置必须是数组');
      }

      const errors: string[] = [];
      parsed.forEach((server: any, index: number) => {
        if (!server.name) {
          errors.push(`服务器 ${index + 1}: 缺少 name`);
        }
        if (!server.command && !server.connection_url) {
          errors.push(`服务器 ${index + 1}: 缺少 command 或 connection_url`);
        }
      });

      if (errors.length > 0) {
        throw new Error(errors.join('；'));
      }

      setValidationStatus({
        isValid: true,
        message: `✓ JSON 格式正确（${parsed.length} 个服务器）`,
        serverCount: parsed.length
      });
      return true;
    } catch (error: any) {
      setValidationStatus({
        isValid: false,
        message: `✗ JSON 错误：${error.message}`
      });
      return false;
    }
  };

  const handleEnabledChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newEnabled = e.target.checked;
    setEnabled(newEnabled);

    if (newEnabled && validationStatus.isValid) {
      try {
        const configs = JSON.parse(configText || '[]');
        onMCPChange(newEnabled, configs);
      } catch {
        onMCPChange(newEnabled, []);
      }
    } else {
      onMCPChange(newEnabled, []);
    }
  };

  const handleConfigChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newText = e.target.value;
    setConfigText(newText);

    if (enabled && validateConfig(newText)) {
      try {
        const configs = JSON.parse(newText || '[]');
        onMCPChange(enabled, configs);
      } catch {
        // Invalid JSON, don't update
      }
    }
  };

  const formatJSON = () => {
    try {
      const parsed = JSON.parse(configText || '[]');
      const formatted = JSON.stringify(parsed, null, 2);
      setConfigText(formatted);
    } catch {
      // Invalid JSON, don't format
    }
  };

  // Helper function to check if a preset is currently selected
  const isPresetSelected = (presetName: string): boolean => {
    try {
      const currentText = configText.trim();
      if (!currentText || currentText === '[]') return false;

      const parsed = JSON.parse(currentText);
      if (!Array.isArray(parsed)) return false;

      return parsed.some(server => server.name === presetName);
    } catch {
      return false;
    }
  };

  const togglePreset = (preset: string) => {
    const presets: Record<string, MCPConfig> = {
      github: {
        name: 'github',
        command: 'npx',
        args: ['-y', '@modelcontextprotocol/server-github'],
        env: {
          GITHUB_PERSONAL_ACCESS_TOKEN: 'your_github_token_here'
        }
      },
      tavily: {
        name: 'tavily',
        command: 'npx',
        args: ['-y', 'tavily-mcp@0.1.2'],
        env: {
          TAVILY_API_KEY: 'your_tavily_api_key_here'
        }
      },
      filesystem: {
        name: 'filesystem',
        command: 'npx',
        args: ['-y', '@modelcontextprotocol/server-filesystem', '/path/to/allowed/directory'],
        env: {}
      }
    };

    const config = presets[preset];
    if (!config) return;

    try {
      let currentConfig: MCPConfig[] = [];
      const currentText = configText.trim();

      if (currentText && currentText !== '[]') {
        currentConfig = JSON.parse(currentText);
      }

      const existingIndex = currentConfig.findIndex(server => server.name === config.name);

      if (existingIndex !== -1) {
        // Remove the preset if it exists (deselect)
        currentConfig.splice(existingIndex, 1);
      } else {
        // Add the preset if it doesn't exist (select)
        currentConfig.push(config);
      }

      const newText = JSON.stringify(currentConfig, null, 2);
      setConfigText(newText);

      // IMPORTANT: Also call onMCPChange immediately with the new config
      if (enabled) {
        onMCPChange(enabled, currentConfig);
      }

    } catch (error) {
      console.error('切换预设时出错:', error);
    }
  };

  const showExample = () => {
    const exampleConfig = [
      {
        name: 'github',
        command: 'npx',
        args: ['-y', '@modelcontextprotocol/server-github'],
        env: {
          GITHUB_PERSONAL_ACCESS_TOKEN: 'your_github_token_here'
        }
      },
      {
        name: 'filesystem',
        command: 'npx',
        args: ['-y', '@modelcontextprotocol/server-filesystem', '/path/to/allowed/directory'],
        env: {}
      }
    ];

    setConfigText(JSON.stringify(exampleConfig, null, 2));
  };

  return (
    <div className="form-group">
      <div className="settings mcp-section">
        <div className="settings mcp-header">
          <label className="agent_question">
            <input
              type="checkbox"
              className="settings mcp-toggle"
              checked={enabled}
              onChange={handleEnabledChange}
            />
            外部工具接入（MCP）
          </label>
          <button
            type="button"
            className="settings mcp-info-btn"
            onClick={() => setShowInfoModal(true)}
            title="了解更多"
          >
            ℹ️
          </button>
        </div>
        <small className="text-muted" style={{ color: 'rgba(255, 255, 255, 0.6)', fontSize: '0.82rem', marginBottom: '10px', display: 'block', lineHeight: '1.5' }}>
          开启后，AI 研究助手可以调用外部服务（GitHub、网页搜索、本地文件等）来辅助完成研究任务。
          <br />
          与下方的"热榜平台管理"互不干扰，两者独立工作。
        </small>

        {enabled && (
          <div className="settings mcp-config-section">
            <div className="settings mcp-presets">
              <label className="agent_question" style={{ marginBottom: '10px' }}>快速预设</label>
              <div className="settings preset-buttons">
                <button
                  type="button"
                  className={`settings preset-btn ${isPresetSelected('github') ? 'selected' : ''}`}
                  onClick={() => togglePreset('github')}
                >
                  <i className="fab fa-github"></i> GitHub
                </button>
                <button
                  type="button"
                  className={`settings preset-btn ${isPresetSelected('tavily') ? 'selected' : ''}`}
                  onClick={() => togglePreset('tavily')}
                >
                  <i className="fas fa-search"></i> Tavily 搜索
                </button>
                <button
                  type="button"
                  className={`settings preset-btn ${isPresetSelected('filesystem') ? 'selected' : ''}`}
                  onClick={() => togglePreset('filesystem')}
                >
                  <i className="fas fa-folder"></i> 本地文件
                </button>
              </div>
              <small className="text-muted" style={{ color: 'rgba(255, 255, 255, 0.5)', fontSize: '0.78rem', marginTop: '6px', display: 'block' }}>
                点击预设即可快速添加/移除对应服务，修改会自动同步到下方 JSON 配置中
              </small>
            </div>

            <div className="settings mcp-config-group">
              <label className="agent_question" style={{ marginBottom: '10px' }}>MCP 服务器配置</label>
              <textarea
                className={`settings mcp-config-textarea ${validationStatus.isValid ? 'valid' : 'invalid'}`}
                rows={12}
                placeholder={"粘贴 MCP 服务器配置（JSON 数组格式），例如：" + JSON.stringify([{ name: "my-server", command: "python", args: ["-m", "my_mcp_server"], env: {} }], null, 2)}
                value={configText}
                onChange={handleConfigChange}
                style={{ minHeight: '300px' }}
              />
              <div className="settings mcp-config-status">
                <span className={`settings mcp-status-text ${validationStatus.isValid ? 'valid' : 'invalid'}`}>
                  {validationStatus.message}
                </span>
                <button
                  type="button"
                  className="settings mcp-format-btn"
                  onClick={formatJSON}
                >
                  <i className="fas fa-code"></i> 格式化 JSON
                </button>
              </div>
              <small className="text-muted" style={{ color: 'rgba(255, 255, 255, 0.5)', fontSize: '0.78rem', marginTop: '8px', display: 'block', lineHeight: '1.5' }}>
                每个服务器需包含{' '}
                <code style={{ backgroundColor: 'rgba(255, 255, 255, 0.1)', padding: '2px 4px', borderRadius: '3px', color: '#0d9488' }}>name</code>、{' '}
                <code style={{ backgroundColor: 'rgba(255, 255, 255, 0.1)', padding: '2px 4px', borderRadius: '3px', color: '#0d9488' }}>command</code>、{' '}
                <code style={{ backgroundColor: 'rgba(255, 255, 255, 0.1)', padding: '2px 4px', borderRadius: '3px', color: '#0d9488' }}>args</code>，可选{' '}
                <code style={{ backgroundColor: 'rgba(255, 255, 255, 0.1)', padding: '2px 4px', borderRadius: '3px', color: '#0d9488' }}>env</code>{' '}
                <a
                  href="#"
                  className="settings mcp-example-link"
                  onClick={(e) => { e.preventDefault(); showExample(); }}
                  style={{ color: '#0d9488', textDecoration: 'none', fontWeight: '500' }}
                >
                  查看示例 →
                </a>
              </small>
            </div>
          </div>
        )}

        {/* 热榜平台管理 —— 每个启用的平台成为一个 Hot List MCP Tool */}
        {onHotPlatformsChange && (
          <HotListPlatforms
            hotPlatforms={hotPlatforms}
            onChange={onHotPlatformsChange}
          />
        )}

        {/* MCP 信息弹窗 */}
        {showInfoModal && (
          <div className="settings mcp-info-modal visible">
            <div className="settings mcp-info-content">
              <button
                className="settings mcp-info-close"
                onClick={() => setShowInfoModal(false)}
              >
                <i className="fas fa-times"></i>
              </button>
              <h3>外部工具接入（MCP 协议）</h3>
              <p>MCP（Model Context Protocol）让 AI 研究助手能够连接外部工具和数据源，扩展研究能力。</p>

              <h4 className="highlight">适用场景：</h4>
              <ul>
                <li><span className="highlight">访问 GitHub</span> — 读取仓库代码、Issue、PR 等</li>
                <li><span className="highlight">网页搜索</span> — 通过 Tavily 等付费引擎获取更精准的搜索结果</li>
                <li><span className="highlight">本地文件</span> — 读取指定目录下的本地文档作为素材</li>
                <li><span className="highlight">自定义服务</span> — 接入自建 MCP 服务器获取专属数据</li>
              </ul>

              <h4 className="highlight">使用步骤：</h4>
              <ul>
                <li>勾选上方"外部工具接入（MCP）"复选框启用</li>
                <li>点击快速预设按钮，一键添加常用服务</li>
                <li>或在下方文本框中粘贴自定义的 MCP 服务器配置</li>
                <li>开始研究时，AI 会自动调用配置的工具</li>
              </ul>

              <h4 className="highlight">⚠️ 注意：</h4>
              <ul>
                <li>此功能用于扩展<strong>通用研究</strong>的数据来源</li>
                <li><strong>热榜报告</strong>所需的热榜平台请在下方"热榜平台管理"中配置</li>
                <li>两者互不干扰，独立工作</li>
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default MCPSelector;
